# Implementation Plan

- [x] 1. Create email service module





  - Create `email_service.py` with SMTP configuration and core email sending functionality
  - Implement `send_email()` function with HTML and plain text support
  - Implement error handling for SMTP connection and authentication failures
  - Add logging for email operations
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 1.1 Write property test for email service


  - **Property 7: Email send returns status**
  - **Validates: Requirements 3.3, 3.4**


- [-] 1.2 Write property test for email format support







  - **Property 8: Email service accepts both text formats**

  - **Validates: Requirements 3.6**



- [ ] 2. Implement course assignment email template


  - Create HTML email template with gradient styling and course details table

  - Create plain text fallback template
  - Implement `send_course_assignment_email()` function with template rendering
  - Add template variables for user_name, course_name, deadline
  - _Requirements: 3.2, 3.6_

- [ ] 3. Implement batch email functionality

  - Create `send_bulk_emails()` function for multiple recipients
  - Track success/failure counts for each recipient
  - Return results dictionary with success, failed counts and failed_emails list
  - _Requirements: 3.7_

- [x] 3.1 Write property test for batch email processing





  - **Property 9: Batch send processes all recipients**
  - **Validates: Requirements 3.7**

- [x] 4. Add search functionality to settings page





  - Add search input field at top of user selection interface in `templates/settings.html`
  - Style search input to match existing UI design
  - Add search results count display ("Showing X of Y users")
  - _Requirements: 1.1_

- [x] 5. Implement real-time search filtering




  - Create `filterUsers()` JavaScript function with substring matching (case-insensitive)
  - Add event listener to search input for real-time filtering
  - Implement `renderUsers()` function to update displayed user list
  - Handle empty search (show all users) and no results (show message)
  - _Requirements: 1.2, 1.3, 1.4, 1.5_

- [x] 5.1 Write property test for search filter




  - **Property 1: Search filter matches substring**
  - **Validates: Requirements 1.2, 1.3**


- [x] 5.2 Write property test for search clear



  - **Property 2: Clear search restores full list**
  - **Validates: Requirements 1.5**


- [x] 6. Implement duplicate user validation (client-side)






  - Create `validateUserEmail()` JavaScript function to check for existing emails
  - Add validation to "Add User" form submission
  - Display error message when duplicate detected
  - Highlight email input field on validation error
  - Prevent form submission when duplicate found
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 6.1 Write property test for duplicate detection


  - **Property 3: Duplicate detection identifies existing emails**
  - **Validates: Requirements 2.1**

- [x] 6.2 Write property test for duplicate addition invariant




  - **Property 4: Duplicate addition preserves list invariant**
  - **Validates: Requirements 2.2, 2.4**

- [x] 6.3 Write property test for error message format


  - **Property 5: Duplicate error message contains email reference**
  - **Validates: Requirements 2.3**
-

- [x] 7. Implement duplicate user validation (server-side)




  - Add duplicate email check to `/api/settings/users` POST endpoint in `app.py`
  - Return 409 Conflict status with error message for duplicates
  - Perform case-insensitive email comparison
  - _Requirements: 2.1, 2.2, 2.4_

- [x] 7.1 Write property test for unique email addition






  - **Property 6: Unique email addition succeeds**
  - **Validates: Requirements 2.5**




- [ ] 8. Integrate email service with course assignment creation

  - Import email service functions in `app.py`
  - Update `/api/settings/assignments` endpoint to send emails after assignment creation
  - Get user names for each assigned user email
  - Call `send_course_assignment_email()` for each assigned user




  - Track and return email send results (success/failed counts)
  - Add error logging for failed email sends
  - _Requirements: 3.2, 3.3, 3.4_

- [ ] 9. Add email notification status to API response

  - Update assignment creation response to include email send statistics
  - Return success/failed email counts in JSON response
  - Ensure assignment is saved even if some emails fail
  - _Requirements: 3.3, 3.4_
