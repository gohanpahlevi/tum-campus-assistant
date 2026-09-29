import React, { useState, useEffect, useRef } from "react";
import "./SecurityGuard.css";

const SecurityGuard = ({ children }) => {
	const [isBlocked, setIsBlocked] = useState(false);
	const [blockReason, setBlockReason] = useState("");
	const [attackType, setAttackType] = useState("");
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState(null);
	const isBlockedRef = useRef(false);

	useEffect(() => {
		validateIP();
	}, []);

	const validateIP = async () => {
		try {
			setIsLoading(true);
			setError(null);

			const token = await generateValidationToken();

			// Backend API configuration - same pattern as ChatWindow
			const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 
				(window.location.hostname === 'localhost' ? "http://localhost:8083" : "");
			
			const response = await fetch(`${API_BASE_URL}/api/v2/security/validate-ip`, {
				method: "GET",
				headers: {
					"Content-Type": "application/json",
					"X-Validation-Token": token,
				},
			});

			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}

			const data = await response.json();

			if (!verifyResponseIntegrity(data)) {
				throw new Error("Response integrity check failed");
			}

			if (data.blocked) {
				setIsBlocked(true);
				isBlockedRef.current = true;
				setBlockReason(data.reason);
				setAttackType(data.attack_type || "unknown");
				blockAllAPICalls();
			} else {
				setIsBlocked(false);
				isBlockedRef.current = false;
			}
		} catch (err) {
			// Only block access for actual security responses (403), not network errors
			if (err.message && err.message.includes("status: 403")) {
				setIsBlocked(true);
				isBlockedRef.current = true;
				setError("Access denied for security reasons.");
			} else {
				setError("Security validation temporarily unavailable. Access allowed.");
				setIsBlocked(false);
				isBlockedRef.current = false;
			}
		} finally {
			setIsLoading(false);
		}
	};

	const generateValidationToken = async () => {
		const timestamp = Date.now();
		const userAgent = navigator.userAgent;
		const token = btoa(`${timestamp}:${userAgent}`).slice(0, 32);
		return token;
	};

	const verifyResponseIntegrity = (data) => {
		return (
			data &&
			typeof data.blocked === "boolean" &&
			typeof data.reason === "string" &&
			data.request_id
		);
	};

	const blockAllAPICalls = () => {
		const originalFetch = window.fetch;
		window.fetch = function (...args) {
			const url = args[0];
			if (typeof url === "string" && url.includes("/api/")) {
				return Promise.reject(new Error("Access denied - IP is blacklisted"));
			}
			return originalFetch.apply(this, args);
		};
		const originalXHROpen = XMLHttpRequest.prototype.open;
		XMLHttpRequest.prototype.open = function (method, url, ...args) {
			if (typeof url === "string" && url.includes("/api/")) {
				throw new Error("Access denied - IP is blacklisted");
			}
			return originalXHROpen.apply(this, [method, url, ...args]);
		};
	};

	if (isLoading) {
		return (
			<div className="security-loading">
				<div className="loading-spinner"></div>
				<p>Validating security status...</p>
			</div>
		);
	}

	if (error) {
		return (
			<div className="security-error">
				<div className="error-container">
					<h2>⚠️ Security Validation Error</h2>
					<p>{error}</p>
					<p className="security-notice-text">
						For security reasons, access has been blocked due to validation
						failure.
					</p>
					<button onClick={validateIP} className="retry-button">
						Retry Validation
					</button>
				</div>
			</div>
		);
	}

	if (isBlocked) {
		return (
			<div className="security-blocked">
				<div className="blocked-container">
					<div className="blocked-icon">🚫</div>
					<h1>Access Denied</h1>
					<h2>Your IP address has been blocked for security reasons</h2>
					<div className="block-details">
						<div className="detail-item">
							<strong>Reason:</strong> {blockReason}
						</div>
						{attackType && attackType !== "unknown" && (
							<div className="detail-item">
								<strong>Attack Type:</strong> {attackType}
							</div>
						)}
						<div className="detail-item">
							<strong>Block Type:</strong> Permanent
						</div>
					</div>
					<div className="block-message">
						<p>
							This IP address has been permanently blacklisted due to malicious
							activity.
						</p>
						<p>Better luck next time!</p>
					</div>
				</div>
			</div>
		);
	}

	return children;
};

export default SecurityGuard;
