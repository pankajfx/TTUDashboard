# Course Analytics Dashboard

A modern Flask-based dashboard for tracking course progress and user engagement.

## Features

- **Real-time Data**: Fetches data from API on page load
- **KPI Cards**: Total courses, users, enrollments, and completion rate
- **Interactive Charts**: 
  - Top 10 courses by enrollment (bar chart)
  - Overall completion status (pie chart)
- **Sortable Table**: Click column headers to sort
- **Export**: Download table data as CSV
- **Modern UI**: Built with Tailwind CSS and ECharts

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Running the Application

1. Start the Flask server:
```bash
python app.py
```

2. Open your browser and navigate to:
```
http://localhost:5000
```

## Project Structure

```
.
├── app.py                  # Flask application
├── templates/
│   └── index.html         # Main dashboard page
├── static/
│   ├── css/
│   │   └── tailwind.min.css
│   └── js/
│       └── echarts.min.js
├── requirements.txt       # Python dependencies
└── README.md
```

## Features Coming Soon

- Course drilldown view (click on any course row)
- User drilldown view with timeline
- Additional analytics and filters
- More export options
