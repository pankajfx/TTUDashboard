"""
Integration tests for server-side duplicate user validation.

These tests verify that the Flask API endpoint properly validates
duplicate emails with case-insensitive comparison and returns
appropriate HTTP status codes.
"""

import json
import os
import tempfile
import pytest
from app import app, USERS_FILE


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    """Create an authenticated test client."""
    # Login as admin
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
    return client


@pytest.fixture
def temp_users_file():
    """Create a temporary users file for testing."""
    # Create a temporary file
    fd, path = tempfile.mkstemp(suffix='.json')
    
    # Write initial test data
    test_data = {
        'users': [
            {
                'email': 'existing@example.com',
                'name': 'Existing User',
                'source': 'manual',
                'added_date': '2024-12-06 10:00:00'
            },
            {
                'email': 'another@example.com',
                'name': 'Another User',
                'source': 'api',
                'added_date': '2024-12-06 10:00:00'
            }
        ]
    }
    
    with os.fdopen(fd, 'w') as f:
        json.dump(test_data, f)
    
    # Temporarily replace the USERS_FILE path
    original_path = app.config.get('USERS_FILE_PATH', USERS_FILE)
    
    yield path
    
    # Cleanup
    try:
        os.unlink(path)
    except:
        pass


def test_add_user_with_duplicate_email_returns_409(authenticated_client, temp_users_file, monkeypatch):
    """
    Test that adding a user with a duplicate email returns 409 Conflict status.
    
    Validates: Requirements 2.1, 2.2
    """
    # Monkey patch the USERS_FILE constant
    import app as app_module
    monkeypatch.setattr(app_module, 'USERS_FILE', temp_users_file)
    
    # Attempt to add a user with an existing email
    response = authenticated_client.post(
        '/api/settings/users',
        data=json.dumps({'email': 'existing@example.com'}),
        content_type='application/json'
    )
    
    # Should return 409 Conflict
    assert response.status_code == 409, \
        f"Expected status code 409 for duplicate email, got {response.status_code}"
    
    # Response should contain error message
    data = json.loads(response.data)
    assert 'error' in data, "Response should contain error message"
    assert 'existing@example.com' in data['error'] or 'already exists' in data['error'].lower(), \
        f"Error message should indicate duplicate: {data['error']}"


def test_add_user_with_duplicate_email_case_insensitive(authenticated_client, temp_users_file, monkeypatch):
    """
    Test that duplicate detection is case-insensitive.
    
    Validates: Requirements 2.1, 2.4
    """
    # Monkey patch the USERS_FILE constant
    import app as app_module
    monkeypatch.setattr(app_module, 'USERS_FILE', temp_users_file)
    
    # Attempt to add a user with different case
    response = authenticated_client.post(
        '/api/settings/users',
        data=json.dumps({'email': 'EXISTING@EXAMPLE.COM'}),
        content_type='application/json'
    )
    
    # Should return 409 Conflict (case-insensitive match)
    assert response.status_code == 409, \
        f"Expected status code 409 for case-insensitive duplicate, got {response.status_code}"
    
    # Try another case variation
    response = authenticated_client.post(
        '/api/settings/users',
        data=json.dumps({'email': 'ExIsTiNg@ExAmPlE.cOm'}),
        content_type='application/json'
    )
    
    assert response.status_code == 409, \
        f"Expected status code 409 for mixed-case duplicate, got {response.status_code}"


def test_add_user_with_unique_email_succeeds(authenticated_client, temp_users_file, monkeypatch):
    """
    Test that adding a user with a unique email succeeds.
    
    Validates: Requirements 2.5
    """
    # Monkey patch the USERS_FILE constant
    import app as app_module
    monkeypatch.setattr(app_module, 'USERS_FILE', temp_users_file)
    
    # Add a user with a unique email
    response = authenticated_client.post(
        '/api/settings/users',
        data=json.dumps({'email': 'newuser@example.com'}),
        content_type='application/json'
    )
    
    # Should return 200 success
    assert response.status_code == 200, \
        f"Expected status code 200 for unique email, got {response.status_code}"
    
    # Response should contain success message
    data = json.loads(response.data)
    assert 'message' in data or 'user' in data, \
        "Response should contain success message or user data"
    
    # Verify user was added to the file
    with open(temp_users_file, 'r') as f:
        users_data = json.load(f)
    
    emails = [u['email'] for u in users_data['users']]
    assert 'newuser@example.com' in emails, \
        "New user should be added to the users list"


def test_duplicate_validation_preserves_list(authenticated_client, temp_users_file, monkeypatch):
    """
    Test that attempting to add a duplicate doesn't modify the user list.
    
    Validates: Requirements 2.2, 2.4
    """
    # Monkey patch the USERS_FILE constant
    import app as app_module
    monkeypatch.setattr(app_module, 'USERS_FILE', temp_users_file)
    
    # Load original users
    with open(temp_users_file, 'r') as f:
        original_data = json.load(f)
    original_count = len(original_data['users'])
    original_emails = [u['email'] for u in original_data['users']]
    
    # Attempt to add duplicate
    response = authenticated_client.post(
        '/api/settings/users',
        data=json.dumps({'email': 'existing@example.com'}),
        content_type='application/json'
    )
    
    # Should fail
    assert response.status_code == 409
    
    # Load users after attempt
    with open(temp_users_file, 'r') as f:
        after_data = json.load(f)
    after_count = len(after_data['users'])
    after_emails = [u['email'] for u in after_data['users']]
    
    # Verify list unchanged
    assert after_count == original_count, \
        f"User count should remain {original_count}, got {after_count}"
    assert after_emails == original_emails, \
        "User list should remain unchanged after duplicate attempt"
