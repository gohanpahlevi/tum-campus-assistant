"""Tests for the parts of the chatbot that run without calling Gemini.

needs_user_info has two layers. The rules below run first and decide most
queries on their own. Only what falls through reaches the model, and those
paths are not covered here.

generate_response is covered with the model stubbed out, so what is tested is
the routing around the call and not the text Gemini writes.
"""

import logging

import pytest

import chatbot_v2
from chatbot_v2 import TUMChatbotV2


class Stub:
    """A chatbot with no model and no knowledge base, for the pure methods."""

    def __init__(self, knowledge_base=None):
        self.logger = logging.getLogger("test")
        self.knowledge_base = knowledge_base or []

    needs_user_info = TUMChatbotV2.needs_user_info
    optimized_search = TUMChatbotV2.optimized_search
    _is_personal_conversation = TUMChatbotV2._is_personal_conversation
    _fallback_extract_context = TUMChatbotV2._fallback_extract_context
    format_response = TUMChatbotV2.format_response


def doc(question, answer="", category="", role="", keywords=()):
    return {
        "question": question,
        "answer": answer,
        "category": category,
        "role": role,
        "keywords": list(keywords),
    }


def test_known_user_is_never_asked_again():
    context = {"role": "student", "campus": "Garching"}
    assert Stub().needs_user_info("Where is the mensa?", context) is None


@pytest.mark.parametrize("query", [
    "Where is the library?",
    "How do I find building 5?",
    "Is there parking on campus?",
])
def test_location_questions_ask_for_the_missing_campus(query):
    assert Stub().needs_user_info(query, {"role": "student"}) == "campus"


def test_non_location_questions_do_not_ask_for_campus():
    assert Stub().needs_user_info("How do I reset my password?", {"role": "student"}) is None


@pytest.mark.parametrize("query", [
    "hello",
    "thanks",
    "I am feeling stressed",
    "how are you",
])
def test_small_talk_never_asks_for_context(query):
    assert Stub().needs_user_info(query, {}) is None


def test_unknown_user_falls_through_to_the_model():
    """The rules cannot answer this one, so it reaches the model layer."""
    stub = Stub()
    asked = []
    stub._ai_needs_context_check = lambda q: asked.append(q) or True
    assert stub.needs_user_info("Where is the mensa?", {"role": "", "campus": ""}) == "both"
    assert asked == ["Where is the mensa?"]


def test_only_the_missing_field_is_requested():
    stub = Stub()
    stub._ai_needs_context_check = lambda q: True
    assert stub.needs_user_info("Where is the mensa?", {"campus": "Garching"}) == "role"


def test_search_returns_nothing_without_a_knowledge_base():
    assert Stub().optimized_search("mensa") == []


def test_search_expands_a_query_to_related_words():
    kb = [
        doc("Where can I eat on campus?", keywords=["mensa"]),
        doc("How do I reset my password?", keywords=["login"]),
    ]
    hits = Stub(kb).optimized_search("I am hungry", top_k=1)
    assert hits[0]["question"] == "Where can I eat on campus?"


def test_search_respects_top_k():
    kb = [doc(f"Question about the mensa {i}", keywords=["mensa"]) for i in range(5)]
    assert len(Stub(kb).optimized_search("mensa", top_k=2)) == 2


def test_search_prefers_documents_matching_the_user_role():
    kb = [
        doc("Parking permits", role="employee", keywords=["parking"]),
        doc("Parking permits", role="student", keywords=["parking"]),
    ]
    hits = Stub(kb).optimized_search("parking", top_k=1, user_context={"role": "employee"})
    assert hits[0]["role"] == "employee"


# format_response


def test_knowledge_entry_labels_never_reach_the_user():
    text = "Knowledge Entry 3: The mensa is in Building 8."
    assert "Entry" not in Stub().format_response(text)


def test_system_names_and_addresses_are_emphasised():
    out = Stub().format_response("Log in to TUMonline or write to it-support@tum.de")
    assert "**TUMonline**" in out
    assert "**it-support@tum.de**" in out


def test_runs_of_blank_lines_are_collapsed():
    assert "\n\n\n" not in Stub().format_response("One.\n\n\n\n\nTwo.")


# _fallback_extract_context, the path used when the model cannot be reached


@pytest.mark.parametrize("query,expected", [
    ("I am a student", {"role": "student"}),
    ("I work here", {"role": "employee"}),
    ("I am visiting", {"role": "visitor"}),
    ("I am at garching", {"campus": "Garching"}),
    ("ich bin in münchen", {"campus": "Munich"}),
    ("bildungscampus", {"campus": "Heilbronn"}),
])
def test_fallback_reads_role_and_campus_from_plain_words(query, expected):
    assert Stub()._fallback_extract_context(query) == expected


def test_fallback_returns_nothing_when_there_is_no_signal():
    assert Stub()._fallback_extract_context("where is the mensa") == {}


# generate_response, with the model stubbed


class FakeModel:
    """Stands in for Gemini. Records prompts and returns a fixed answer."""

    def __init__(self, answer="The mensa is in Building 8.", error=None):
        self.answer = answer
        self.error = error
        self.prompts = []

    def generate_content(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return type("Reply", (), {"text": self.answer})()


class Chatbot(Stub):
    """Enough of the real object to exercise generate_response."""

    def __init__(self, knowledge_base=None, model=None, context=None):
        super().__init__(knowledge_base)
        self.model = model or FakeModel()
        if context is None:
            context = {"role": "student", "campus": "Garching"}
        self.user_sessions = {
            "s1": {
                "user_context": context,
                "conversation_history": [],
                "pending_question": None,
                "awaiting_context": False,
            }
        }

    def extract_user_info(self, query, session_id):
        return False

    generate_response = TUMChatbotV2.generate_response


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """Keep the tests off the statistics database and the chat session log."""
    monkeypatch.setattr(chatbot_v2.stats_manager, "record_chat_interaction", lambda *a, **k: None)
    monkeypatch.setattr(chatbot_v2, "log_chat_session", lambda *a, **k: None)


def test_a_known_user_gets_an_answer_and_the_model_is_called():
    bot = Chatbot([doc("Where can I eat?", answer="Mensa, Building 8", keywords=["mensa"])])
    assert bot.generate_response("where is the mensa", "s1") == "The mensa is in Building 8."
    assert len(bot.model.prompts) == 1


def test_retrieved_entries_are_put_in_the_prompt():
    bot = Chatbot([doc("Where can I eat?", answer="Mensa, Building 8", keywords=["mensa"])])
    bot.generate_response("where is the mensa", "s1")
    assert "Mensa, Building 8" in bot.model.prompts[0]


def test_an_unknown_user_is_asked_for_context_and_the_model_is_not_called():
    bot = Chatbot(context={})
    bot._ai_needs_context_check = lambda q: True
    reply = bot.generate_response("where is the mensa", "s1")
    assert "role" in reply and "campus" in reply
    assert bot.model.prompts == []


def test_the_original_question_is_held_while_context_is_collected():
    bot = Chatbot(context={})
    bot._ai_needs_context_check = lambda q: True
    bot.generate_response("where is the mensa", "s1")
    session = bot.user_sessions["s1"]
    assert session["pending_question"] == "where is the mensa"
    assert session["awaiting_context"] is True


def test_the_held_question_is_answered_once_context_arrives():
    bot = Chatbot([doc("Where can I eat?", answer="Mensa, Building 8", keywords=["mensa"])], context={})
    bot._ai_needs_context_check = lambda q: True
    bot.generate_response("where is the mensa", "s1")

    bot.extract_user_info = lambda query, session_id: True
    bot.user_sessions["s1"]["user_context"] = {"role": "student", "campus": "Garching"}
    bot.generate_response("student at garching", "s1")

    session = bot.user_sessions["s1"]
    assert session["pending_question"] is None
    assert session["awaiting_context"] is False
    assert "where is the mensa" in bot.model.prompts[0]


def test_a_failing_model_does_not_raise_at_the_caller():
    bot = Chatbot(model=FakeModel(error=RuntimeError("quota exceeded")))
    reply = bot.generate_response("where is the mensa", "s1")
    assert "servicedesk@tum.de" in reply


def test_history_stays_bounded_however_long_the_conversation_runs():
    """The trim runs after the question is added and before the answer is,
    so the list settles at 13 and not at the 12 the trim asks for."""
    bot = Chatbot()
    for i in range(40):
        bot.generate_response(f"question {i}", "s1")
    assert len(bot.user_sessions["s1"]["conversation_history"]) == 13
