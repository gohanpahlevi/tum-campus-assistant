"""Tests for the parts of the chatbot that run without calling Gemini.

needs_user_info has two layers. The rules below run first and decide most
queries on their own. Only what falls through reaches the model, and those
paths are not covered here.
"""

import logging

import pytest

from chatbot_v2 import TUMChatbotV2


class Stub:
    """A chatbot with no model and no knowledge base, for the pure methods."""

    def __init__(self, knowledge_base=None):
        self.logger = logging.getLogger("test")
        self.knowledge_base = knowledge_base or []

    needs_user_info = TUMChatbotV2.needs_user_info
    optimized_search = TUMChatbotV2.optimized_search
    _is_personal_conversation = TUMChatbotV2._is_personal_conversation


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
