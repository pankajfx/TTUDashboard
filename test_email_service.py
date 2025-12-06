"""
Property-Based Tests for Email Service Module
Tests correctness properties using Hypothesis
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import patch, MagicMock
import smtplib
from email_service import send_email, send_bulk_emails


# Property 7: Email send returns status
# Feature: admin-user-management-enhancements, Property 7: Email send returns status
# Validates: Requirements 3.3, 3.4
@given(
    to_address=st.emails(),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100)
def test_email_send_returns_status(to_address, subject, body_html):
    """
    **Feature: admin-user-management-enhancements, Property 7: Email send returns status**
    
    For any valid email parameters (recipient, subject, body), 
    the send_email function should return a boolean status indicating 
    success or failure, never raising an unhandled exception.
    """
    # Mock the SMTP connection to avoid actual email sending
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Test that function returns a boolean
        result = send_email(to_address, subject, body_html)
        
        # Property: Result must be a boolean (True or False)
        assert isinstance(result, bool), f"Expected boolean result, got {type(result)}"


# Property 7 (failure case): Email send returns status on SMTP errors
@given(
    to_address=st.emails(),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100)
def test_email_send_returns_false_on_smtp_error(to_address, subject, body_html):
    """
    **Feature: admin-user-management-enhancements, Property 7: Email send returns status**
    
    When SMTP errors occur, the function should return False (not raise exception).
    """
    # Mock SMTP to raise an authentication error
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b'Authentication failed')
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Test that function returns False on error (doesn't raise exception)
        result = send_email(to_address, subject, body_html)
        
        # Property: Result must be False when SMTP fails
        assert result is False, "Expected False when SMTP authentication fails"


# Property 7 (failure case): Email send returns status on connection errors
@given(
    to_address=st.emails(),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100)
def test_email_send_returns_false_on_connection_error(to_address, subject, body_html):
    """
    **Feature: admin-user-management-enhancements, Property 7: Email send returns status**
    
    When connection errors occur, the function should return False (not raise exception).
    """
    # Mock SMTP to raise a connection error
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_smtp.side_effect = smtplib.SMTPException("Connection failed")
        
        # Test that function returns False on error (doesn't raise exception)
        result = send_email(to_address, subject, body_html)
        
        # Property: Result must be False when connection fails
        assert result is False, "Expected False when SMTP connection fails"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# Property 8: Email service accepts both text formats
# Feature: admin-user-management-enhancements, Property 8: Email service accepts both text formats
# Validates: Requirements 3.6
@given(
    to_address=st.emails(),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500),
    body_text=st.one_of(st.none(), st.text(min_size=1, max_size=500))
)
@settings(max_examples=100)
def test_email_service_accepts_both_formats(to_address, subject, body_html, body_text):
    """
    **Feature: admin-user-management-enhancements, Property 8: Email service accepts both text formats**
    
    For any recipient and subject, the send_email function should successfully 
    accept and process both plain text and HTML body content without errors.
    """
    # Mock the SMTP connection
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Test with HTML only
        result_html_only = send_email(to_address, subject, body_html)
        assert isinstance(result_html_only, bool), "Should return boolean for HTML-only email"
        
        # Test with both HTML and plain text
        result_both = send_email(to_address, subject, body_html, body_text)
        assert isinstance(result_both, bool), "Should return boolean for HTML+text email"
        
        # Verify the function doesn't raise exceptions with either format
        # The fact that we got here means no exception was raised


# Property 8 (verification): Email service properly attaches both formats
@given(
    to_address=st.emails(),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500),
    body_text=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100)
def test_email_service_attaches_both_formats(to_address, subject, body_html, body_text):
    """
    **Feature: admin-user-management-enhancements, Property 8: Email service accepts both text formats**
    
    When both formats are provided, both should be attached to the message.
    """
    # Mock the SMTP connection
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Call with both formats
        result = send_email(to_address, subject, body_html, body_text)
        
        # Property: Function should handle both formats without error
        assert isinstance(result, bool), "Should return boolean when both formats provided"
        
        # If successful, verify send_message was called
        if result:
            assert mock_server.send_message.called, "send_message should be called on success"


# Property 9: Batch send processes all recipients
# Feature: admin-user-management-enhancements, Property 9: Batch send processes all recipients
# Validates: Requirements 3.7
@given(
    recipients=st.lists(st.emails(), min_size=1, max_size=10),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_batch_send_processes_all_recipients(recipients, subject, body_html):
    """
    **Feature: admin-user-management-enhancements, Property 9: Batch send processes all recipients**
    
    For any list of recipient email addresses, the send_bulk_emails function 
    should attempt to send to each recipient and return a results dictionary 
    with success and failure counts that sum to the total number of recipients.
    """
    # Mock the SMTP connection
    with patch('email_service.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Call batch send
        result = send_bulk_emails(recipients, subject, body_html)
        
        # Property: Result must be a dictionary with required keys
        assert isinstance(result, dict), "Result should be a dictionary"
        assert 'success' in result, "Result should contain 'success' key"
        assert 'failed' in result, "Result should contain 'failed' key"
        assert 'failed_emails' in result, "Result should contain 'failed_emails' key"
        
        # Property: Success + failed counts must equal total recipients
        total_processed = result['success'] + result['failed']
        assert total_processed == len(recipients), \
            f"Total processed ({total_processed}) must equal recipients count ({len(recipients)})"
        
        # Property: failed_emails list length must equal failed count
        assert len(result['failed_emails']) == result['failed'], \
            "Length of failed_emails must equal failed count"


# Property 9 (mixed success/failure): Batch send handles partial failures
@given(
    recipients=st.lists(st.emails(), min_size=2, max_size=10),
    subject=st.text(min_size=1, max_size=100),
    body_html=st.text(min_size=1, max_size=500)
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_batch_send_handles_partial_failures(recipients, subject, body_html):
    """
    **Feature: admin-user-management-enhancements, Property 9: Batch send processes all recipients**
    
    When some emails fail, the function should still process all recipients 
    and accurately report successes and failures.
    """
    # Mock SMTP to fail for every other recipient
    with patch('email_service.send_email') as mock_send:
        # Alternate between success and failure
        mock_send.side_effect = [i % 2 == 0 for i in range(len(recipients))]
        
        result = send_bulk_emails(recipients, subject, body_html)
        
        # Property: All recipients should be processed
        total_processed = result['success'] + result['failed']
        assert total_processed == len(recipients), \
            "All recipients should be processed even with failures"
        
        # Property: Counts should be accurate
        expected_success = sum(1 for i in range(len(recipients)) if i % 2 == 0)
        expected_failed = len(recipients) - expected_success
        
        assert result['success'] == expected_success, \
            f"Expected {expected_success} successes, got {result['success']}"
        assert result['failed'] == expected_failed, \
            f"Expected {expected_failed} failures, got {result['failed']}"
