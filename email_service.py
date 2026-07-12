"""
Email Notification Service Module
Handles sending email notifications for course assignments and reminders
"""

import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SMTP Configuration
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SENDER_ADDRESS = SMTP_USERNAME


def send_email(to_address, subject, body_html, body_text=None):
    """
    Send an email notification
    
    Args:
        to_address (str): Recipient email address
        subject (str): Email subject
        body_html (str): HTML body content
        body_text (str, optional): Plain text body content
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        logger.info(f"Attempting to send email to {to_address} with subject: {subject}")
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_ADDRESS
        msg['To'] = to_address
        msg['Subject'] = subject
        
        # Add plain text version if provided
        if body_text:
            part1 = MIMEText(body_text, 'plain')
            msg.attach(part1)
            logger.debug("Added plain text body to email")
        
        # Add HTML version
        part2 = MIMEText(body_html, 'html')
        msg.attach(part2)
        logger.debug("Added HTML body to email")
        
        # Connect to SMTP server
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            logger.debug(f"Connected to SMTP server {SMTP_SERVER}:{SMTP_PORT} with TLS")
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            logger.debug("SMTP authentication successful")
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_address}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email to {to_address}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_address}: {e}")
        return False


def send_course_assignment_email(user_email, user_name, course_name, deadline):
    """
    Send course assignment notification to user with styled HTML template
    
    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the assigned course
        deadline (str): Course completion deadline (YYYY-MM-DD)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    subject = f"📚 New Course Assignment: {course_name}"
    
    # Enhanced HTML email template optimized for both desktop and mobile
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
        
        /* Base styles */
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: #ffffff; 
            padding: 20px 15px;
            text-align: center;
        }}
        
        .header-icon {{
            font-size: 36px;
            margin-bottom: 8px;
        }}
        
        .header h1 {{ 
            margin: 0; 
            font-size: 22px; 
            font-weight: 600;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        
        .content {{ 
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .greeting {{
            font-size: 15px;
            color: #333333;
            margin-bottom: 15px;
        }}
        
        .message-box {{
            background: #f0f4ff;
            border-left: 4px solid #667eea;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .details-table {{ 
            width: 100%; 
            margin: 20px 0;
            border-collapse: collapse;
            background: #ffffff;
        }}
        
        .details-table td {{ 
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        
        .details-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .label {{ 
            font-weight: 600; 
            color: #667eea;
            width: 40%;
        }}
        
        .value {{
            color: #333333;
            font-weight: 500;
        }}
        
        .cta-button {{ 
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff !important;
            padding: 12px 28px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            margin: 15px 0;
            text-align: center;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        /* Mobile responsive */
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
            .header {{ padding: 18px 12px; }}
            .header h1 {{ font-size: 20px; }}
            .cta-button {{ padding: 10px 22px; font-size: 14px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="header-icon">📚 <span class="label" style="white-space:nowrap; font-size:18px;">New Course Assignment </span></div>
        </div>
            <div class="message-box">
                <p style="margin: 0; font-size: 14px;">
                    <p style="font-weight:600">Dear {user_name},</p> <p>A new course has been assigned to you as part of our Safety & Health Excellence program. Kindly ignore if already completed.</p>
                </p>
            </div>

            <table class="details-table">
                <tr>
                    <td class="label">📖 Course Name:</td>
                    <td class="value">{course_name}</td>
                </tr>
                <tr>
                    <td class="label">📅 Deadline:</td>
                    <td class="value">{deadline}</td>
                </tr>
            </table>

            <p style="margin: 15px 0; font-size: 14px; color: #495057;">
                Please log in to the Tata Tomorrow University portal to access your course materials and begin your learning journey.
            </p>

            <center>
                <a href="https://www.tmtctata.com/" class="cta-button"
                   style="display:inline-block;background:#667eea;color:#ffffff;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px;margin:15px 0;">
                    Access Course Portal
                </a>
            </center>

        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    # Plain text fallback template
    body_text = f"""Dear {user_name},

A new course has been assigned to you as part of our Safety & Health Excellence program. Kindly ignore if already completed.

Course Details:
📖 Course Name: {course_name}
📅 Deadline: {deadline}

Please log in to the Tata Tomorrow University portal to access your course materials:
https://www.tmtctata.com/

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""
    
    return send_email(user_email, subject, body_html, body_text)


def send_deadline_reminder_email(user_email, user_name, course_name, deadline, days_remaining):
    """
    Send deadline reminder notification to user
    
    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the course
        deadline (str): Course completion deadline
        days_remaining (int): Days remaining until deadline
    """
    subject = f"⏰ REMINDER: Course Deadline - {course_name}"
    
    urgency_color = "#ef4444" if days_remaining <= 3 else "#f59e0b"
    urgency_text = "URGENT" if days_remaining <= 3 else "Important"
    
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .header {{ 
            background: linear-gradient(135deg, {urgency_color} 0%, #dc2626 100%); 
            color: #ffffff; 
            padding: 20px 15px;
            text-align: center;
        }}
        
        .header-icon {{
            font-size: 36px;
            margin-bottom: 8px;
        }}
        
        .header h1 {{ 
            margin: 0; 
            font-size: 22px; 
            font-weight: 600;
            color: #ffffff;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        
        .urgency-badge {{ 
            background: rgba(255, 255, 255, 0.3);
            color: #ffffff;
            padding: 5px 14px;
            border-radius: 20px;
            display: inline-block;
            font-weight: 600;
            font-size: 12px;
            margin-top: 8px;
        }}
        
        .content {{ 
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .alert-box {{
            background: #fff3cd;
            border-left: 4px solid {urgency_color};
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .details-table {{ 
            width: 100%; 
            margin: 20px 0;
            border-collapse: collapse;
            background: #ffffff;
        }}
        
        .details-table td {{ 
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        
        .details-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .label {{ 
            font-weight: 600; 
            color: {urgency_color};
            width: 45%;
        }}
        
        .value {{
            color: #333333;
            font-weight: 500;
        }}
        
        .days-remaining {{
            color: {urgency_color};
            font-weight: 700;
            font-size: 18px;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
            .header {{ padding: 18px 12px; }}
            .header h1 {{ font-size: 20px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="header-icon">⏰</div>
            <h1>Course Deadline Reminder</h1>
            <span class="urgency-badge">{urgency_text}</span>
        </div>
        
        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>
            
            <div class="alert-box">
                <p style="margin: 0; font-size: 14px; font-weight: 600;">
                    ⚠️ Your course deadline is approaching!
                </p>
            </div>
            
            <table class="details-table">
                <tr>
                    <td class="label">📖 Course Name:</td>
                    <td class="value">{course_name}</td>
                </tr>
                <tr>
                    <td class="label">📅 Final Deadline:</td>
                    <td class="value">{deadline}</td>
                </tr>
                <tr>
                    <td class="label">⏳ Days Remaining:</td>
                    <td class="days-remaining">{days_remaining} days</td>
                </tr>
            </table>
            
            <p style="margin: 15px 0; font-size: 14px; color: #495057;">
                Please complete this course before the deadline to ensure your progress is recorded and compliance requirements are met.
            </p>

            <div style="text-align:center;margin:0 0 8px;">
                <a href="https://www.tmtctata.com/"
                   style="display:inline-block;background:{urgency_color};color:#ffffff;padding:13px 32px;text-decoration:none;border-radius:6px;font-weight:600;font-size:15px;letter-spacing:0.3px;">
                    Access Course Portal
                </a>
            </div>
        </div>
        
        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated reminder. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    body_text = f"""⏰ REMINDER: Course Deadline Approaching

Dear {user_name},

This is a reminder that your course deadline is approaching!

Course Details:
📖 Course Name: {course_name}
📅 Final Deadline: {deadline}
⏳ Days Remaining: {days_remaining} days

Please complete this course before the deadline to ensure your progress is recorded.

Access the Tata Tomorrow University portal here:
https://www.tmtctata.com/

Regards,
Safety & Health Excellence Support Team

---
This is an automated reminder."""
    
    return send_email(user_email, subject, body_html, body_text)


def send_course_removal_email(user_email, user_name, course_name):
    """
    Send notification when user is removed from a course assignment
    
    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the course
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    subject = f"Course Assignment Removed: {course_name}"
    
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .header {{ 
            background: linear-gradient(135deg, #6b7280 0%, #4b5563 100%); 
            color: #ffffff; 
            padding: 20px 15px;
            text-align: center;
        }}
        
        .header-icon {{
            font-size: 36px;
            margin-bottom: 8px;
        }}
        
        .header h1 {{ 
            margin: 0; 
            font-size: 22px; 
            font-weight: 600;
            color: #ffffff;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        
        .content {{ 
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .info-box {{ 
            background: #f3f4f6;
            border-left: 4px solid #6b7280;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
            .header {{ padding: 18px 12px; }}
            .header h1 {{ font-size: 20px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="header-icon">ℹ️</div>
            <h1>Course Assignment Update</h1>
        </div>
        
        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>
            
            <p style="font-size: 14px; color: #495057; margin: 12px 0;">
                This is to inform you that you have been removed from the following course assignment:
            </p>
            
            <div class="info-box">
                <p style="margin: 0; font-size: 14px;">
                    <strong>📖 Course:</strong> {course_name}
                </p>
            </div>
            
            <p style="font-size: 14px; color: #495057; margin: 15px 0;">
                You are no longer required to complete this course. If you believe this is an error, please contact your administrator.
            </p>
        </div>
        
        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    body_text = f"""Course Assignment Update

Dear {user_name},

This is to inform you that you have been removed from the following course assignment:

📖 Course: {course_name}

You are no longer required to complete this course. If you believe this is an error, please contact your administrator.

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""
    
    return send_email(user_email, subject, body_html, body_text)


def send_course_completion_email(user_email, user_name, course_name, completion_date,
                                 deadline=None):
    """
    Congratulate a user who has completed a course they were assigned.

    Sent automatically by the API sync the first time a completion is detected inside
    an assignment's validity window (see app.dispatch_completion_notifications). Each
    (assignment, user) pair is emailed exactly once — the completion_notifications
    ledger in db.py guarantees it.

    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the completed course
        completion_date (str): Date the course was completed (YYYY-MM-DD)
        deadline (str, optional): The assignment deadline, shown when known

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    subject = f"✅ Course Completed: {course_name}"

    on_time_note = ""
    if deadline and completion_date:
        try:
            done = datetime.strptime(str(completion_date)[:10], '%Y-%m-%d')
            due = datetime.strptime(str(deadline)[:10], '%Y-%m-%d')
            if done <= due:
                on_time_note = (
                    '<p style="font-size: 14px; color: #047857; margin: 12px 0; '
                    'font-weight: 600;">🎯 Completed within the deadline — well done!</p>')
        except (ValueError, TypeError):
            on_time_note = ""

    deadline_row = ""
    if deadline:
        deadline_row = f"""
                <p style="margin: 8px 0 0 0; font-size: 14px;">
                    <strong>⏰ Deadline:</strong> {deadline}
                </p>"""

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5;
            color: #333333;
            margin: 0;
            padding: 0;
            background-color: #f4f4f4;
        }}

        .email-container {{
            max-width: 600px;
            margin: 15px auto;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        .header {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: #ffffff;
            padding: 20px 15px;
            text-align: center;
        }}

        .header-icon {{
            font-size: 36px;
            margin-bottom: 8px;
        }}

        .header h1 {{
            margin: 0;
            font-size: 22px;
            font-weight: 600;
            color: #ffffff;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}

        .content {{
            padding: 20px 20px;
            background: #ffffff;
        }}

        .info-box {{
            background: #ecfdf5;
            border-left: 4px solid #10b981;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}

        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}

        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}

        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}

        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
            .header {{ padding: 18px 12px; }}
            .header h1 {{ font-size: 20px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="header-icon">🎉</div>
            <h1>Course Completed</h1>
        </div>

        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>

            <p style="font-size: 14px; color: #495057; margin: 12px 0;">
                Congratulations! Our records show that you have successfully completed the
                course assigned to you.
            </p>

            <div class="info-box">
                <p style="margin: 0; font-size: 14px;">
                    <strong>📖 Course:</strong> {course_name}
                </p>
                <p style="margin: 8px 0 0 0; font-size: 14px;">
                    <strong>✅ Completed on:</strong> {completion_date or 'Recently'}
                </p>{deadline_row}
            </div>

            {on_time_note}

            <p style="font-size: 14px; color: #495057; margin: 15px 0;">
                Thank you for your commitment to safety and continuous learning. No further
                action is required for this course.
            </p>
        </div>

        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety &amp; Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""

    body_text = f"""Course Completed

Dear {user_name},

Congratulations! Our records show that you have successfully completed the course assigned to you.

📖 Course: {course_name}
✅ Completed on: {completion_date or 'Recently'}
{f'⏰ Deadline: {deadline}' if deadline else ''}

Thank you for your commitment to safety and continuous learning. No further action is required for this course.

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""

    return send_email(user_email, subject, body_html, body_text)


def send_bulk_emails(recipients, subject, body_html, body_text=None):
    """
    Send email to multiple recipients

    Args:
        recipients (list): List of email addresses
        subject (str): Email subject
        body_html (str): HTML body content
        body_text (str, optional): Plain text body content
    
    Returns:
        dict: Results with success/failure counts
    """
    results = {'success': 0, 'failed': 0, 'failed_emails': []}
    
    for email in recipients:
        if send_email(email, subject, body_html, body_text):
            results['success'] += 1
        else:
            results['failed'] += 1
            results['failed_emails'].append(email)
    
    return results


# Template functions for common email types
def get_assignment_email_template(course_name, deadline):
    """Get HTML template for course assignment email"""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">New Course Assignment</h2>
            <p>Hello,</p>
            <p>You have been assigned a new course:</p>
            
            <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Course:</strong> {course_name}</p>
                <p style="margin: 5px 0;"><strong>Deadline:</strong> {deadline}</p>
            </div>
            
            <p>Please complete this course by the deadline.</p>
            
            <p style="margin-top: 30px; color: #666; font-size: 12px;">
                This is an automated notification from the Course Analytics Dashboard.
            </p>
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    # Test email functionality
    print("Email Service Module")
    print(f"SMTP Server: {SMTP_SERVER}:{SMTP_PORT}")
    print(f"Sender: {SENDER_ADDRESS}")
    print("\nReady to send notifications!")
