"""
Firestore-based Security module for TUM Chatbot V2
Implements prompt injection detection and IP blacklisting using Google Firestore
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

try:
    from google.cloud import firestore
    from google.cloud.firestore import Client
except ImportError:
    firestore = None
    Client = None

try:
    from .config import get_config
    from .logger import get_logger
    from .security import SecurityEvent, PromptInjectionDetector
except ImportError:
    from config import get_config
    from logger import get_logger
    from security import SecurityEvent, PromptInjectionDetector

logger = get_logger(__name__)

class FirestoreBlacklistManager:
    """Manages IP blacklisting with Firestore for persistence across Cloud Run instances"""
    
    def __init__(self):
        self.config = get_config()
        if firestore is None:
            raise ImportError("google-cloud-firestore is required for Firestore security")
        
        # Initialize Firestore client
        self.db: Client = firestore.Client()
        
        # Collection names
        self.blacklist_collection = "ip_blacklist"
        self.violations_collection = "ip_violations" 
        self.events_collection = "security_events"
        
        logger.info("Firestore security manager initialized")
    
    def is_blacklisted(self, ip_address: str) -> bool:
        """Check if IP is blacklisted"""
        try:
            doc_ref = self.db.collection(self.blacklist_collection).document(ip_address)
            doc = doc_ref.get()
            return doc.exists
        except Exception as e:
            logger.error(f"Error checking Firestore blacklist: {e}")
            return False
    
    def add_to_blacklist(self, ip_address: str, attack_type: str, reason: str, 
                        confidence: float, blacklisted_by: str = "system") -> bool:
        """Add IP to permanent blacklist"""
        try:
            doc_ref = self.db.collection(self.blacklist_collection).document(ip_address)
            
            # Check if already exists
            existing_doc = doc_ref.get()
            now = datetime.utcnow()
            
            if existing_doc.exists:
                # Update existing entry
                doc_ref.update({
                    "attempt_count": firestore.Increment(1),
                    "last_updated": now
                })
                logger.warning(f"IP {ip_address} already blacklisted. Updated attempt_count and last_updated.")
            else:
                # Add new entry
                doc_ref.set({
                    "ip_address": ip_address,
                    "attack_type": attack_type,
                    "reason": reason,
                    "confidence": confidence,
                    "first_detected": now,
                    "last_updated": now,
                    "attempt_count": 1,
                    "blacklisted_by": blacklisted_by
                })
                logger.warning(f"IP BLACKLISTED: ip={ip_address}, attack_type={attack_type}, reason={reason}, confidence={confidence}, first_detected={now}, blacklisted_by={blacklisted_by}")
            
            return True
                
        except Exception as e:
            logger.error(f"Error adding to Firestore blacklist: {e}")
            return False
    
    def track_violation(self, ip_address: str) -> int:
        """Track violation for IP and return current count"""
        try:
            doc_ref = self.db.collection(self.violations_collection).document(ip_address)
            
            # Use a transaction to ensure atomicity
            @firestore.transactional
            def update_violation_count(transaction):
                doc = doc_ref.get(transaction=transaction)
                now = datetime.utcnow()
                
                if doc.exists:
                    # Update existing violation count
                    current_count = doc.get("violation_count") or 0
                    new_count = current_count + 1
                    transaction.update(doc_ref, {
                        "violation_count": new_count,
                        "last_violation": now
                    })
                    return new_count
                else:
                    # First violation
                    transaction.set(doc_ref, {
                        "ip_address": ip_address,
                        "violation_count": 1,
                        "first_violation": now,
                        "last_violation": now
                    })
                    return 1
            
            # Execute transaction
            transaction = self.db.transaction()
            new_count = update_violation_count(transaction)
            
            logger.info(f"IP {ip_address} violation count: {new_count}")
            return new_count
                
        except Exception as e:
            logger.error(f"Error tracking violation in Firestore: {e}")
            return 0
    
    def record_security_event(self, event: SecurityEvent) -> bool:
        """Record security event for analysis"""
        try:
            doc_ref = self.db.collection(self.events_collection).document()
            doc_ref.set({
                "timestamp": event.timestamp,
                "ip_address": event.ip_address,
                "user_id": event.user_id,
                "session_id": event.session_id,
                "query": event.query,
                "attack_type": event.attack_type,
                "confidence": event.confidence,
                "detection_method": event.detection_method,
                "response_generated": event.response_generated,
                "blacklisted": event.blacklisted
            })
            return True
                
        except Exception as e:
            logger.error(f"Error recording security event in Firestore: {e}")
            return False
    
    def get_blacklist_stats(self) -> Dict[str, Any]:
        """Get blacklist statistics"""
        try:
            # Total blacklisted IPs
            blacklist_docs = self.db.collection(self.blacklist_collection).get()
            total_blacklisted = len(blacklist_docs)
            
            # Attack type breakdown
            attack_breakdown = {}
            blacklisted_ips = []
            
            for doc in blacklist_docs:
                data = doc.to_dict()
                attack_type = data.get("attack_type", "unknown")
                attack_breakdown[attack_type] = attack_breakdown.get(attack_type, 0) + 1
                
                blacklisted_ips.append({
                    "ip_address": data.get("ip_address"),
                    "attack_type": attack_type,
                    "reason": data.get("reason"),
                    "confidence": data.get("confidence"),
                    "first_detected": data.get("first_detected"),
                    "attempt_count": data.get("attempt_count", 1)
                })
            
            # Recent events (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(days=1)
            recent_events_query = self.db.collection(self.events_collection).where("timestamp", ">", yesterday)
            recent_events = len(list(recent_events_query.get()))
            
            return {
                "total_blacklisted": total_blacklisted,
                "attack_breakdown": attack_breakdown,
                "recent_events_24h": recent_events,
                "blacklisted_ips": blacklisted_ips
            }
                
        except Exception as e:
            logger.error(f"Error getting Firestore blacklist stats: {e}")
            return {}

class FirestoreSecurityManager:
    """Main security manager using Firestore for persistence"""
    
    def __init__(self, gemini_client):
        self.config = get_config()
        self.detector = PromptInjectionDetector(gemini_client)
        self.blacklist_manager = FirestoreBlacklistManager()
        logger.info("Firestore security manager initialized")
    
    def analyze_request(self, user_input: str, ip_address: str, user_id: str, 
                       session_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Analyze request for security threats
        Returns: (should_block, security_info)
        """
        # Check if IP is already blacklisted
        if self.blacklist_manager.is_blacklisted(ip_address):
            logger.warning(f"Blocked request from blacklisted IP: {ip_address}")
            return True, {
                "blocked": True,
                "reason": "IP blacklisted",
                "attack_type": "blacklisted_ip",
                "confidence": 1.0
            }
        
        # Perform prompt injection detection
        try:
            detection_result = self.detector.detect_injection(user_input)
            
            # Create security event
            event = SecurityEvent(
                timestamp=datetime.utcnow(),
                ip_address=ip_address,
                user_id=user_id,
                session_id=session_id,
                query=user_input,
                attack_type=detection_result["attack_type"],
                confidence=detection_result["confidence"],
                detection_method="llm_detection",
                response_generated=not detection_result["is_attack"],
                blacklisted=False
            )
            
            # Record the security event
            self.blacklist_manager.record_security_event(event)
            
            # If attack detected, track violation and check threshold
            if detection_result["is_attack"] and detection_result["confidence"] >= self.config.security.detection_confidence_threshold:
                # Track violation count
                violation_count = self.blacklist_manager.track_violation(ip_address)
                
                # Check if we should blacklist (reached threshold)
                should_blacklist = violation_count >= self.config.security.violation_threshold
                
                if should_blacklist:
                    # Blacklist the IP permanently
                    reason = f"{detection_result['attack_type']}: {detection_result['reasoning']}"
                    self.blacklist_manager.add_to_blacklist(
                        ip_address, 
                        detection_result["attack_type"], 
                        reason, 
                        detection_result["confidence"]
                    )
                    
                    # Update event to reflect blacklisting
                    event.blacklisted = True
                    self.blacklist_manager.record_security_event(event)
                    
                    logger.warning(f"IP {ip_address} BLACKLISTED after {violation_count} violations: {detection_result}")
                    return True, {
                        "blocked": True,
                        "reason": f"IP blacklisted after {violation_count} violations",
                        "attack_type": detection_result["attack_type"],
                        "confidence": detection_result["confidence"],
                        "severity": detection_result["severity"],
                        "violation_count": violation_count
                    }
                else:
                    # Block this request but don't blacklist yet
                    event.blacklisted = False
                    self.blacklist_manager.record_security_event(event)
                    
                    logger.warning(f"Attack blocked from {ip_address} (violation {violation_count}/{self.config.security.violation_threshold}): {detection_result}")
                    return True, {
                        "blocked": True,
                        "reason": f"Attack detected: {detection_result['attack_type']} (warning {violation_count}/{self.config.security.violation_threshold})",
                        "attack_type": detection_result["attack_type"],
                        "confidence": detection_result["confidence"],
                        "severity": detection_result["severity"],
                        "violation_count": violation_count
                    }
            
            return False, {
                "blocked": False,
                "attack_type": detection_result["attack_type"],
                "confidence": detection_result["confidence"],
                "severity": detection_result["severity"]
            }
            
        except Exception as e:
            logger.error(f"Detection LLM failed: {e}")
            return True, {
                "blocked": True,
                "reason": "We are having trouble verifying your question at the moment, please try again later.",
                "attack_type": "detection_error",
                "confidence": 1.0,
                "severity": "high"
            }
    
    def get_security_stats(self) -> Dict[str, Any]:
        """Get security statistics"""
        return self.blacklist_manager.get_blacklist_stats()