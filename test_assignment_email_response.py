"""
Test for assignment creation API response with email notification status
Tests Requirements 3.3, 3.4
"""

import pytest
import json
import os
from unittest.mock import patch, MagicMock
from app import app, load_json_file, save_json_file


@pytest.fixture
def client():
    """Create test client"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
        yield client


@pytest.fixture
def setup_test_data():
    """Setup test data files"""
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)
    
    # Create test users
    users_data = {
        'users': [
            {'email': 'test1@example.com', 'name': 'Test User 1', 'source': 'manual'},
            {'email': 'test2@example.com', 'name': 'Test User 2', 'source': 'manual'}
        ]
    }
    save_json_file('data/users.json', users_data)
    
    # Create empty assignments file
    save_json_file('data/course_assignments.json', {'assignments': []})
    
    yield
    
    # Cleanup is optional since we're using real files


def test_assignment_response_includes_email_statistics(client, setup_test_data):
    """
    Test that assignment creation response includes email send statistics
    Validates: Requirements 3.3, 3.4
    """
    # Mock the email service to control success/failure
    with patch('app.send_course_assignment_email') as mock_email:
        # First email succeeds, second fails
        mock_email.side_effect = [True, False]
        
        # Create assignment
        response = client.post('/api/settings/assignments', 
            json={
                'course_name': 'Test Course',
                'user_emails': ['test1@example.com', 'test2@example.com'],
                'deadline': '2024-12-31'
            },
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        # Verify response structure
        assert 'message' in data
        assert 'assignment' in data
        assert 'emails_sent' in data
        assert 'emails_failed' in data
        assert 'failed_emails' in data
        
        # Verify email statistics
        assert data['emails_sent'] == 1
        assert data['emails_failed'] == 1
        assert len(data['failed_emails']) == 1
        assert 'test2@example.com' in data['failed_emails']


def test_assignment_saved_even_if_all_emails_fail(client, setup_test_data):
    """
    Test that assignment is saved even if all email notifications fail
    Validates: Requirements 3.3, 3.4
    """
    # Mock email service to fail all emails
    with patch('app.send_course_assignment_email') as mock_email:
        mock_email.return_value = False
        
        # Create assignment
        response = client.post('/api/settings/assignments',
            json={
                'course_name': 'Test Course 2',
                'user_emails': ['test1@example.com', 'test2@example.com'],
                'deadline': '2024-12-31'
            },
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        # Verify assignment was created
        assert data['message'] == 'Assignment created successfully'
        assert data['assignment']['course_name'] == 'Test Course 2'
        
        # Verify all emails failed
        assert data['emails_sent'] == 0
        assert data['emails_failed'] == 2
        assert len(data['failed_emails']) == 2
        
        # Verify assignment was actually saved to file
        assignments = load_json_file('data/course_assignments.json', {'assignments': []})
        assert len(assignments['assignments']) > 0
        # Find our assignment
        found = False
        for assignment in assignments['assignments']:
            if assignment['course_name'] == 'Test Course 2':
                found = True
                break
        assert found, "Assignment should be saved even when all emails fail"


def test_assignment_response_with_all_emails_successful(client, setup_test_data):
    """
    Test that response correctly reports when all emails succeed
    Validates: Requirements 3.3, 3.4
    """
    with patch('app.send_course_assignment_email') as mock_email:
        mock_email.return_value = True
        
        response = client.post('/api/settings/assignments',
            json={
                'course_name': 'Test Course 3',
                'user_emails': ['test1@example.com', 'test2@example.com'],
                'deadline': '2024-12-31'
            },
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        # Verify all emails succeeded
        assert data['emails_sent'] == 2
        assert data['emails_failed'] == 0
        assert len(data['failed_emails']) == 0


def test_email_statistics_sum_to_total_recipients(client, setup_test_data):
    """
    Test that success + failed counts equal total recipients
    Validates: Requirements 3.3, 3.4
    """
    with patch('app.send_course_assignment_email') as mock_email:
        # Mix of success and failure
        mock_email.side_effect = [True, False, True, False, True]
        
        user_emails = [f'test{i}@example.com' for i in range(5)]
        
        response = client.post('/api/settings/assignments',
            json={
                'course_name': 'Test Course 4',
                'user_emails': user_emails,
                'deadline': '2024-12-31'
            },
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        # Verify counts sum correctly
        total_recipients = len(user_emails)
        assert data['emails_sent'] + data['emails_failed'] == total_recipients
        assert len(data['failed_emails']) == data['emails_failed']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
