"""
Property-based tests for duplicate user validation functionality.

These tests validate the duplicate detection logic that prevents adding
users with existing email addresses.
"""

from hypothesis import given, strategies as st, settings, HealthCheck
from hypothesis.strategies import composite


@composite
def user_strategy(draw):
    """Generate a user object with email and optional name."""
    email = draw(st.emails())
    # Generate name or None
    has_name = draw(st.booleans())
    name = draw(st.text(alphabet=st.characters(whitelist_categories=('L', 'N')), min_size=1, max_size=20)) if has_name else None
    
    return {
        'email': email,
        'name': name,
        'source': draw(st.sampled_from(['api', 'manual'])),
        'added_date': '2024-12-06 10:30:00'
    }


def validate_user_email(email, users):
    """
    Python implementation of the JavaScript validateUserEmail logic.
    
    Checks if an email already exists in the user list (case-insensitive).
    
    Args:
        email: Email address to validate
        users: List of existing user objects
    
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    # Check if email exists in users list (case-insensitive)
    email_lower = email.lower()
    
    for user in users:
        if user['email'].lower() == email_lower:
            return {
                'valid': False,
                'error': f"User with email '{email}' already exists"
            }
    
    return {
        'valid': True,
        'error': ''
    }


@given(st.lists(user_strategy(), min_size=0, max_size=20), st.emails())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_duplicate_detection_identifies_existing_emails(users, test_email):
    """
    **Feature: admin-user-management-enhancements, Property 3: Duplicate detection identifies existing emails**
    
    For any user list and any email address, the duplicate validation function 
    should return true if and only if that email already exists in the list 
    (case-insensitive comparison).
    
    **Validates: Requirements 2.1**
    """
    # Get list of existing emails (case-insensitive)
    existing_emails = [user['email'].lower() for user in users]
    
    # Validate the test email
    result = validate_user_email(test_email, users)
    
    # Check if test_email exists in the list
    email_exists = test_email.lower() in existing_emails
    
    # Validation should fail if and only if email exists
    if email_exists:
        assert not result['valid'], \
            f"Email '{test_email}' exists in list but validation passed"
        assert result['error'], \
            f"Email '{test_email}' exists but no error message provided"
    else:
        assert result['valid'], \
            f"Email '{test_email}' does not exist but validation failed"
        assert result['error'] == '', \
            f"Email '{test_email}' does not exist but error message was provided"



def add_user_if_valid(email, users):
    """
    Python implementation of adding a user with validation.
    
    Attempts to add a user to the list only if the email is unique.
    
    Args:
        email: Email address to add
        users: List of existing user objects (will be modified in place)
    
    Returns:
        dict with 'success' (bool) and 'message' (str) keys
    """
    # Validate email first
    validation = validate_user_email(email, users)
    
    if not validation['valid']:
        # Duplicate detected - do not modify the list
        return {
            'success': False,
            'message': validation['error']
        }
    
    # Email is unique - add the user
    new_user = {
        'email': email,
        'name': None,
        'source': 'manual',
        'added_date': '2024-12-06 10:30:00'
    }
    users.append(new_user)
    
    return {
        'success': True,
        'message': 'User added successfully'
    }


@given(st.lists(user_strategy(), min_size=0, max_size=20), st.emails())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_duplicate_addition_preserves_list_invariant(users, duplicate_email):
    """
    **Feature: admin-user-management-enhancements, Property 4: Duplicate addition preserves list invariant**
    
    For any user list, attempting to add a user with a duplicate email 
    should not change the length or contents of the user list.
    
    **Validates: Requirements 2.2, 2.4**
    """
    # Only test when the email actually exists in the list
    if not any(user['email'].lower() == duplicate_email.lower() for user in users):
        # Add the email first to make it a duplicate
        users.append({
            'email': duplicate_email,
            'name': 'Test User',
            'source': 'manual',
            'added_date': '2024-12-06 10:30:00'
        })
    
    # Store original state
    original_length = len(users)
    original_emails = [user['email'] for user in users]
    original_users = [user.copy() for user in users]
    
    # Attempt to add duplicate
    result = add_user_if_valid(duplicate_email, users)
    
    # Verify addition failed
    assert not result['success'], \
        f"Adding duplicate email '{duplicate_email}' should have failed"
    
    # Verify list length unchanged
    assert len(users) == original_length, \
        f"List length changed from {original_length} to {len(users)} after duplicate addition attempt"
    
    # Verify list contents unchanged
    current_emails = [user['email'] for user in users]
    assert current_emails == original_emails, \
        f"List contents changed after duplicate addition attempt"



@given(st.lists(user_strategy(), min_size=1, max_size=20))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_duplicate_error_message_contains_email_reference(users):
    """
    **Feature: admin-user-management-enhancements, Property 5: Duplicate error message contains email reference**
    
    For any duplicate email validation error, the error message should contain 
    either the word "email" or the actual email address that caused the conflict.
    
    **Validates: Requirements 2.3**
    """
    # Pick an existing user's email to test duplicate detection
    existing_user = users[0]
    duplicate_email = existing_user['email']
    
    # Validate the duplicate email
    result = validate_user_email(duplicate_email, users)
    
    # Should fail validation
    assert not result['valid'], \
        f"Validation should fail for duplicate email '{duplicate_email}'"
    
    # Error message should exist
    assert result['error'], \
        f"Error message should be provided for duplicate email"
    
    # Error message should contain either "email" or the actual email address
    error_message_lower = result['error'].lower()
    email_lower = duplicate_email.lower()
    
    contains_email_word = 'email' in error_message_lower
    contains_email_address = email_lower in error_message_lower
    
    assert contains_email_word or contains_email_address, \
        f"Error message '{result['error']}' should contain either 'email' or the email address '{duplicate_email}'"


@given(st.lists(user_strategy(), min_size=0, max_size=20), st.emails())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_unique_email_addition_succeeds(users, unique_email):
    """
    **Feature: admin-user-management-enhancements, Property 6: Unique email addition succeeds**
    
    For any user list and any email that doesn't exist in the list, adding a user 
    with that email should increase the list length by one and include the new user.
    
    **Validates: Requirements 2.5**
    """
    # Ensure the email is unique by removing any existing instances
    users = [user for user in users if user['email'].lower() != unique_email.lower()]
    
    # Store original state
    original_length = len(users)
    original_emails = {user['email'].lower() for user in users}
    
    # Verify email doesn't exist
    assert unique_email.lower() not in original_emails, \
        f"Test setup failed: email '{unique_email}' should not exist in the list"
    
    # Attempt to add unique email
    result = add_user_if_valid(unique_email, users)
    
    # Verify addition succeeded
    assert result['success'], \
        f"Adding unique email '{unique_email}' should have succeeded but got: {result['message']}"
    
    # Verify list length increased by one
    assert len(users) == original_length + 1, \
        f"List length should increase from {original_length} to {original_length + 1}, but got {len(users)}"
    
    # Verify the new user is in the list
    current_emails = {user['email'].lower() for user in users}
    assert unique_email.lower() in current_emails, \
        f"New email '{unique_email}' should be in the user list after addition"
    
    # Verify the new user has the correct email
    added_user = next((user for user in users if user['email'].lower() == unique_email.lower()), None)
    assert added_user is not None, \
        f"Should be able to find the newly added user with email '{unique_email}'"
    assert added_user['email'] == unique_email, \
        f"Added user email should be '{unique_email}' but got '{added_user['email']}'"
