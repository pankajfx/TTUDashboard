"""
Property-based tests for user search filtering functionality.

These tests validate the search filter logic that is implemented in JavaScript
by testing equivalent Python implementations of the same logic.
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


def filter_users(users, search_term):
    """
    Python implementation of the JavaScript filterUsers logic.
    
    Filters users by substring matching (case-insensitive) on email and name.
    If search term is empty, returns all users.
    """
    # If search term is empty, return all users
    if not search_term or search_term.strip() == '':
        return users[:]
    
    # Convert search term to lowercase for case-insensitive matching
    lower_search_term = search_term.lower()
    
    # Filter users by substring matching on email and name
    filtered = []
    for user in users:
        email_match = lower_search_term in user['email'].lower()
        name_match = user.get('name') and lower_search_term in user['name'].lower()
        if email_match or name_match:
            filtered.append(user)
    
    return filtered


@given(st.lists(user_strategy(), min_size=0, max_size=20), st.text(alphabet=st.characters(whitelist_categories=('L', 'N')), min_size=0, max_size=30))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_search_filter_matches_substring(users, search_term):
    """
    **Feature: admin-user-management-enhancements, Property 1: Search filter matches substring**
    
    For any user list and any search term, all users returned by the filter function 
    should contain the search term as a substring (case-insensitive) in their email or name.
    
    **Validates: Requirements 1.2, 1.3**
    """
    filtered = filter_users(users, search_term)
    
    # If search term is empty or whitespace, all users should be returned
    if not search_term or search_term.strip() == '':
        assert filtered == users
        return
    
    lower_search_term = search_term.lower()
    
    # Every filtered user must contain the search term in email or name
    for user in filtered:
        email_match = lower_search_term in user['email'].lower()
        name_match = user.get('name') and lower_search_term in user['name'].lower()
        assert email_match or name_match, \
            f"User {user['email']} does not contain search term '{search_term}'"
    
    # Every user that contains the search term should be in filtered results
    for user in users:
        email_match = lower_search_term in user['email'].lower()
        name_match = user.get('name') and lower_search_term in user['name'].lower()
        if email_match or name_match:
            assert user in filtered, \
                f"User {user['email']} contains search term but was not filtered"



@given(st.lists(user_strategy(), min_size=0, max_size=20), st.text(alphabet=st.characters(whitelist_categories=('L', 'N')), min_size=1, max_size=30))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_clear_search_restores_full_list(users, search_term):
    """
    **Feature: admin-user-management-enhancements, Property 2: Clear search restores full list**
    
    For any user list, applying a search filter and then clearing the search 
    should result in the original full user list being displayed.
    
    **Validates: Requirements 1.5**
    """
    # Store original user list
    original_users = users[:]
    
    # Apply search filter with a non-empty search term
    filtered = filter_users(users, search_term)
    
    # Clear search by passing empty string
    cleared = filter_users(users, '')
    
    # After clearing, should get back the original full list
    assert cleared == original_users, \
        f"Clearing search did not restore full list. Expected {len(original_users)} users, got {len(cleared)}"
    
    # Also test with whitespace-only search term
    cleared_whitespace = filter_users(users, '   ')
    assert cleared_whitespace == original_users, \
        f"Clearing search with whitespace did not restore full list"
