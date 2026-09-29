"""
Flask API for TUM Chatbot V2 - Smart Context Management
"""

import uuid
import time
import base64
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import traceback

try:
    from .config import get_config, validate_config
    from .logger import get_logger, RequestLogger, log_error
    from .chatbot_v2 import TUMChatbotV2
    from .statistics import stats_manager
    from .firestore_security import FirestoreSecurityManager
except ImportError:
    from config import get_config, validate_config
    from logger import get_logger, RequestLogger, log_error
    from chatbot_v2 import TUMChatbotV2
    from statistics import stats_manager
    from firestore_security import FirestoreSecurityManager

logger = get_logger(__name__)

class TUMChatbotAPIV2:
    """Flask API for TUM Chatbot V2"""
    
    def __init__(self):
        self.config = get_config()
        self.app = Flask(__name__)
        self.chatbot = TUMChatbotV2()
        
        # Initialize security manager
        if self.config.security.enable_security:
            self.security_manager = FirestoreSecurityManager(self.chatbot.model)
            logger.info("Firestore security manager initialized")
        else:
            self.security_manager = None
            logger.info("Security disabled")
        
        # Setup CORS
        if self.config.security.enable_cors:
            CORS(self.app, origins=self.config.get_cors_origins_list())
        
        # Setup rate limiting
        if self.config.security.enable_rate_limiting:
            self.limiter = Limiter(
                app=self.app,
                key_func=get_remote_address,
                default_limits=[f"{self.config.security.rate_limit_requests} per {self.config.security.rate_limit_window} seconds"]
            )
        
        # Setup IP validation middleware
        self._setup_ip_validation_middleware()
        
        # Setup routes
        self._setup_routes()
        
        # Error handlers
        self._setup_error_handlers()
    
    def _get_client_ip(self):
        """Extract the real client IP from headers (Cloud Run: X-Forwarded-For)"""
        x_forwarded_for = request.headers.get('X-Forwarded-For', '')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
            if ip:
                return ip
        return request.remote_addr

    def _setup_ip_validation_middleware(self):
        """Setup middleware to validate IP on all requests"""
        
        @self.app.before_request
        def validate_ip_middleware():
            # Skip validation for security endpoints to avoid infinite loops
            if request.endpoint in ['validate_ip', 'get_security_stats']:
                return None
            
            # Skip validation for health check
            if request.endpoint == 'health_check':
                return None
            
            client_ip = self._get_client_ip()
            
            # Check if IP is blacklisted
            if self.security_manager and self.security_manager.blacklist_manager.is_blacklisted(client_ip):
                logger.warning(f"Blocked request from blacklisted IP: {client_ip} to {request.endpoint}")
                return self._error_response("This IP address has been permanently blacklisted due to malicious activity. Better luck next time!", 403)
            
            return None
        
        logger.info("TUM Chatbot API V2 initialized successfully")
        
        if self.config.logging.log_chat_sessions:
            logger.warning(
                "Chat session logging is on in %s. API requests are written to %s, "
                "which includes user data. Set LOG_CHAT_SESSIONS=False to stop it.",
                self.config.environment, self.config.logging.chat_session_file,
            )
    
    def _setup_routes(self):
        """Setup API routes"""
        
        # /api/health is the path people and uptime checks try first, so it is
        # served here too. Both map to the endpoint name the IP middleware skips.
        @self.app.route('/api/health', methods=['GET'])
        @self.app.route('/api/v2/health', methods=['GET'])
        def health_check():
            """Health check endpoint"""
            return jsonify({
                'status': 'healthy',
                'version': 'v2-smart-context',
                'timestamp': datetime.utcnow().isoformat(),
                'environment': self.config.environment
            })
        
        @self.app.route('/api/v2/chat', methods=['POST'])
        def chat():
            """Main chat endpoint with smart context management"""
            request_id = str(uuid.uuid4())
            user_id = request.headers.get('X-User-ID', 'anonymous')
            ip_address = self._get_client_ip()
            
            # Get session_id from JSON body first, then headers, then default
            data = request.get_json() if request.is_json else {}
            session_id = data.get('session_id') or request.headers.get('X-Session-ID', 'default')
            
            with RequestLogger(logger, user_id, session_id, request_id):
                try:
                    if not request.is_json:
                        return self._error_response("Request must be JSON", 400, request_id)
                    
                    # data already retrieved above for session_id
                    message = data.get('message', '').strip()
                    
                    if not message:
                        return self._error_response("Message is required", 400, request_id)
                    
                    if len(message) > 1000:
                        return self._error_response("Message too long (max 1000 characters)", 400, request_id)
                    
                    # Security analysis
                    if self.security_manager and self.config.security.enable_prompt_injection_detection:
                        should_block, security_info = self.security_manager.analyze_request(
                            message, ip_address, user_id, session_id
                        )
                        
                        if should_block:
                            logger.warning(f"Security block: {security_info}")
                            
                            # Use the exact message from security system for detection errors
                            if security_info.get('attack_type') == 'detection_error':
                                error_message = security_info['reason']
                            else:
                                error_message = f"Request blocked for security reasons: {security_info['reason']}"
                            
                            return self._error_response(error_message, 403, request_id)
                    
                    # Start session if needed
                    if session_id not in self.chatbot.user_sessions:
                        self.chatbot.start_session(session_id, user_id)
                    
                    # Generate response
                    response = self.chatbot.generate_response(message, session_id, user_id)
                    
                    return jsonify({
                        'response': response,
                        'session_id': session_id,
                        'request_id': request_id,
                        'version': 'v2',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "chat endpoint V2", user_id, session_id)
                    return self._error_response("Internal server error", 500, request_id)
        
        @self.app.route('/api/v2/session/start', methods=['POST'])
        def start_session():
            """Start a new chat session"""
            try:
                user_id = request.headers.get('X-User-ID', 'anonymous')
                session_id = str(uuid.uuid4())
                self.chatbot.start_session(session_id, user_id)
                return jsonify({
                    'session_id': session_id,
                    'message': 'Session started successfully'
                })
            except Exception as e:
                logger.error(f"Error starting session: {e}")
                return jsonify({'error': 'Failed to start session'}), 500
        
        @self.app.route('/api/v2/session/<session_id>', methods=['DELETE'])
        def end_session(session_id):
            """End a chat session"""
            try:
                self.chatbot.end_session(session_id)
                return jsonify({'message': 'Session ended successfully'})
            except Exception as e:
                logger.error(f"Error ending session: {e}")
                return jsonify({'error': 'Failed to end session'}), 500
        
        @self.app.route('/api/v2/statistics', methods=['GET'])
        def get_statistics():
            """Get usage statistics"""
            request_id = str(uuid.uuid4())
            user_id = request.headers.get('X-User-ID', 'anonymous')
            
            with RequestLogger(logger, user_id, "statistics", request_id):
                try:
                    days = request.args.get('days', 30, type=int)
                    if days < 1 or days > 365:
                        return self._error_response("Days must be between 1 and 365", 400, request_id)
                    
                    stats = stats_manager.get_statistics(days)
                    
                    return jsonify({
                        'statistics': stats,
                        'request_id': request_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "get_statistics endpoint", user_id, "statistics")
                    return self._error_response("Internal server error", 500, request_id)
        
        @self.app.route('/api/v2/statistics/performance', methods=['GET'])
        def get_performance_metrics():
            """Get performance metrics"""
            request_id = str(uuid.uuid4())
            user_id = request.headers.get('X-User-ID', 'anonymous')
            
            with RequestLogger(logger, user_id, "performance", request_id):
                try:
                    days = request.args.get('days', 7, type=int)
                    if days < 1 or days > 30:
                        return self._error_response("Days must be between 1 and 30", 400, request_id)
                    
                    metrics = stats_manager.get_performance_metrics(days)
                    
                    return jsonify({
                        'performance_metrics': metrics,
                        'request_id': request_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "get_performance_metrics endpoint", user_id, "performance")
                    return self._error_response("Internal server error", 500, request_id)
        
        @self.app.route('/api/v2/stats', methods=['GET'])
        def get_stats():
            """Simple stats endpoint (alias for /api/v2/statistics)"""
            request_id = str(uuid.uuid4())
            user_id = request.headers.get('X-User-ID', 'anonymous')
            
            with RequestLogger(logger, user_id, "stats", request_id):
                try:
                    days = request.args.get('days', 30, type=int)
                    if days < 1 or days > 365:
                        return self._error_response("Days must be between 1 and 365", 400, request_id)
                    
                    stats = stats_manager.get_statistics(days)
                    
                    return jsonify({
                        'stats': stats,
                        'request_id': request_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "get_stats endpoint", user_id, "stats")
                    return self._error_response("Internal server error", 500, request_id)
        
        @self.app.route('/api/v2/security/stats', methods=['GET'])
        def get_security_stats():
            """Get security statistics and blacklist information"""
            request_id = str(uuid.uuid4())
            user_id = request.headers.get('X-User-ID', 'anonymous')
            
            with RequestLogger(logger, user_id, "security_stats", request_id):
                try:
                    if not self.security_manager:
                        return self._error_response("Security is disabled", 400, request_id)
                    
                    security_stats = self.security_manager.get_security_stats()
                    
                    return jsonify({
                        'security_stats': security_stats,
                        'request_id': request_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "get_security_stats endpoint", user_id, "security_stats")
                    return self._error_response("Internal server error", 500, request_id)
        
        @self.app.route('/api/v2/security/validate-ip', methods=['GET'])
        def validate_ip():
            """Validate if the requesting IP is blacklisted"""
            request_id = str(uuid.uuid4())
            
            client_ip = self._get_client_ip()
            
            # Validate token if provided
            validation_token = request.headers.get('X-Validation-Token')
            if validation_token:
                # Basic token validation (in production, use proper JWT)
                try:
                    # Decode and validate token format
                    decoded = base64.b64decode(validation_token + '==').decode('utf-8')
                    if ':' not in decoded:
                        logger.warning(f"Invalid validation token format from {client_ip}")
                        return self._error_response("Invalid security token", 403, request_id)
                except Exception:
                    logger.warning(f"Invalid validation token from {client_ip}")
                    return self._error_response("Invalid security token", 403, request_id)
            
            with RequestLogger(logger, "system", "ip_validation", request_id):
                try:
                    if not self.security_manager:
                        return jsonify({
                            'blocked': False,
                            'reason': 'Security disabled',
                            'request_id': request_id,
                            'timestamp': datetime.utcnow().isoformat()
                        })
                    
                    # Check if IP is blacklisted
                    is_blacklisted = self.security_manager.blacklist_manager.is_blacklisted(client_ip)
                    
                    if is_blacklisted:
                        # Get blacklist details from Firestore
                        try:
                            doc_ref = self.security_manager.blacklist_manager.db.collection('ip_blacklist').document(client_ip)
                            doc = doc_ref.get()
                            
                            if doc.exists:
                                blacklist_data = doc.to_dict()
                                return jsonify({
                                    'blocked': True,
                                    'reason': f"IP blacklisted: {blacklist_data.get('reason', 'Security violation')}",
                                    'attack_type': blacklist_data.get('attack_type', 'unknown'),
                                    'confidence': blacklist_data.get('confidence', 1.0),
                                    'first_detected': blacklist_data.get('first_detected', '').isoformat() if blacklist_data.get('first_detected') else '',
                                    'request_id': request_id,
                                    'timestamp': datetime.utcnow().isoformat()
                                })
                        except Exception as e:
                            logger.error(f"Error fetching blacklist details: {e}")
                            # Return blocked status even if we can't get details
                            return jsonify({
                                'blocked': True,
                                'reason': 'IP blacklisted',
                                'attack_type': 'blacklisted_ip',
                                'request_id': request_id,
                                'timestamp': datetime.utcnow().isoformat()
                            })
                    
                    return jsonify({
                        'blocked': False,
                        'reason': 'IP not blacklisted',
                        'request_id': request_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    log_error(e, "validate_ip endpoint", "system", "ip_validation")
                    return self._error_response("Internal server error", 500, request_id)
    
    def _setup_error_handlers(self):
        """Setup error handlers"""
        
        @self.app.errorhandler(404)
        def not_found(error):
            return self._error_response("Endpoint not found", 404)
        
        @self.app.errorhandler(405)
        def method_not_allowed(error):
            return self._error_response("Method not allowed", 405)
        
        @self.app.errorhandler(500)
        def internal_error(error):
            logger.error(f"Internal server error: {error}")
            return self._error_response("Internal server error", 500)
        
        @self.app.errorhandler(Exception)
        def handle_exception(error):
            logger.error(f"Unhandled exception: {error}")
            logger.error(traceback.format_exc())
            return self._error_response("Internal server error", 500)
    
    def _error_response(self, message: str, status_code: int, request_id: Optional[str] = None) -> tuple:
        """Create standardized error response"""
        response_data = {
            'error': message,
            'status_code': status_code,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if request_id:
            response_data['request_id'] = request_id
        
        response = make_response(jsonify(response_data), status_code)
        response.headers['Content-Type'] = 'application/json'
        return response

# Create API instance
api_v2_instance = TUMChatbotAPIV2()
app = api_v2_instance.app  # For Gunicorn compatibility

if __name__ == '__main__':
    config = get_config()
    api_v2_instance.app.run(debug=config.server.debug, host=config.server.host, port=config.server.port)