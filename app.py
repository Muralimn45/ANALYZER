import os
import io
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed

# Imports for Flask and ReportLab
from flask import Flask, render_template_string, request, send_file, jsonify
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4, A3, A2, A1, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# Configure logging for better error messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configuration settings
app.config.update({
    'MAX_FILE_SIZE': 150 * 1024 * 1024,  # 150MB max file size
    'ALLOWED_EXTENSIONS': {'csv', 'xlsx'}
})
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_secure_default_key')
app.config['DEBUG'] = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1')


def allowed_file(filename: str) -> bool:
    """Checks if a file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def generate_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    """Generates a summary DataFrame of descriptive statistics."""
    summary_df = df.describe().reset_index()
    summary_df = summary_df.rename(columns={'index': 'Statistic'}).round(2)
    return summary_df


def generate_reportlab_pdf(df: pd.DataFrame, filename: str) -> io.BytesIO:
    """Generates a summary PDF report."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>Data Analysis Report: {filename}</b>", styles["Title"]))
    story.append(Paragraph(f"<i>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Total Records:</b> {len(df)}", styles["Normal"]))
    story.append(Spacer(1, 24))

    numeric_summary = generate_summary_df(df)
    numeric_data = [list(numeric_summary.columns)] + numeric_summary.values.tolist()

    if not numeric_summary.empty:
        story.append(Paragraph("<b>Numeric Column Statistics:</b>", styles["h2"]))
        table = Table(numeric_data)
        table.setStyle(TableStyle(
            [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')), ('GRID', (0, 0), (-1, -1), 1, colors.black)]))
        story.append(table)
    else:
        story.append(Paragraph("<i>No numeric columns found.</i>", styles['Italic']))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_full_data_pdf(df: pd.DataFrame, filename: str, page_size) -> io.BytesIO:
    """
    Generates a PDF containing the entire CSV data using chunked processing
    to improve performance and reduce memory usage for large files.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=page_size)
    styles = getSampleStyleSheet()
    story = []

    # Title and Metadata
    story.append(Paragraph(f"<b>Full Data Report: {filename}</b>", styles["Title"]))
    story.append(Paragraph(f"<i>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Prepare the header row for the table
    header_data = [list(df.columns)]

    # Define table style once with improved alignment and padding
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
    ])

    # Append the header as the first table
    header_table = Table(header_data)
    header_table.setStyle(table_style)
    story.append(header_table)

    # Process the data in chunks to avoid memory issues and improve rendering speed
    chunk_size = 5000  # Adjust this value based on performance tuning
    total_rows = len(df)

    for i in range(0, total_rows, chunk_size):
        chunk_df = df.iloc[i:i + chunk_size]
        chunk_data = chunk_df.values.tolist()

        # Create a new table for each chunk of data
        chunk_table = Table(chunk_data)
        # Apply the same style, but without the header background
        chunk_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(chunk_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_csv_report(df: pd.DataFrame, report_type: str) -> io.BytesIO:
    """Generates a CSV file from a DataFrame."""
    buffer = io.BytesIO()
    if report_type == 'summary':
        summary_df = generate_summary_df(df)
        summary_df.to_csv(buffer, index=False)
    else:
        df.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


def generate_excel_report(df: pd.DataFrame, report_type: str) -> io.BytesIO:
    """Generates an Excel (xlsx) file from a DataFrame."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        if report_type == 'summary':
            summary_df = generate_summary_df(df)
            summary_df.to_excel(writer, index=False, sheet_name='Summary')
        else:
            df.to_excel(writer, index=False, sheet_name='Full Data')
    buffer.seek(0)
    return buffer


@app.route('/', methods=['GET', 'POST'])
def upload_and_analyze():
    """Main endpoint for the web application."""
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed. Please upload a CSV or Excel file.'}), 400
        try:
            file_bytes = file.read()
            if len(file_bytes) > app.config['MAX_FILE_SIZE']:
                max_mb = app.config['MAX_FILE_SIZE'] / (1024 * 1024)
                return jsonify({'error': f'File is too large. Max size is {int(max_mb)}MB.'}), 400

            filename = secure_filename(file.filename)
            file_extension = filename.rsplit('.', 1)[1].lower()
            df = None

            if file_extension == 'csv':
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes))
                except Exception as e:
                    logger.error("Failed to parse CSV file: %s", e)
                    return jsonify({'error': f'Failed to parse CSV file: {str(e)}'}), 400
            elif file_extension == 'xlsx':
                try:
                    df = pd.read_excel(io.BytesIO(file_bytes))
                except Exception as e:
                    logger.error("Failed to parse Excel file: %s", e)
                    return jsonify({'error': f'Failed to parse Excel file: {str(e)}'}), 400

            # Sanitize column names
            df.columns = df.columns.str.strip().str.lower().str.replace(r'[^a-z0-9_]', '_', regex=True).str.replace(
                r'_+', '_', regex=True)

            report_type = request.form.get('report_type', 'summary').lower()
            output_format = request.form.get('output_format', 'pdf').lower()
            page_size_str = request.form.get('page_size', 'A4')

            report_file = None
            download_name = filename.rsplit('.', 1)[0]
            mimetype = 'application/octet-stream'

            if output_format == 'pdf':
                page_size = A4
                if page_size_str == 'A3':
                    page_size = landscape(A3)
                elif page_size_str == 'A2':
                    page_size = landscape(A2)
                elif page_size_str == 'A1':
                    page_size = landscape(A1)

                if report_type == 'summary':
                    report_file = generate_reportlab_pdf(df, filename)
                    download_name = f'{download_name}_summary_report.pdf'
                elif report_type == 'full_data':
                    report_file = generate_full_data_pdf(df, filename, page_size)
                    download_name = f'{download_name}_full_data.pdf'
                mimetype = 'application/pdf'

            elif output_format == 'csv':
                report_file = generate_csv_report(df, report_type)
                if report_type == 'summary':
                    download_name = f'{download_name}_summary_report.csv'
                else:
                    download_name = f'{download_name}_full_data.csv'
                mimetype = 'text/csv'

            elif output_format == 'excel':
                report_file = generate_excel_report(df, report_type)
                if report_type == 'summary':
                    download_name = f'{download_name}_summary_report.xlsx'
                else:
                    download_name = f'{download_name}_full_data.xlsx'
                mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

            else:
                return jsonify({'error': 'Invalid output format selected'}), 400

            if not report_file:
                return jsonify({'error': 'Failed to generate report'}), 500

            report_file.seek(0)
            return send_file(
                report_file,
                download_name=download_name,
                as_attachment=True,
                mimetype=mimetype
            )
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
            logger.error("CSV/Excel parsing error: %s", e)
            return jsonify({'error': f"Failed to parse the file: {e}"}), 400
        except Exception as e:
            logger.error("An unexpected error occurred: %s", e)
            return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

    return render_template_string('''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Versatile Data Report Generator</title>
        <style>
            :root { --primary: #4a6fa5; --secondary: #166088; --light: #f8f9fa; --dark: #343a40; --success: #28a745; --danger: #dc3545; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; margin: 0; padding: 0; background-color: #f5f7fa; color: #333; }
            .container { max-width: 800px; margin: 2rem auto; padding: 2rem; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
            h1 { color: var(--secondary); text-align: center; margin-bottom: 1.5rem; }
            .upload-form { display: flex; flex-direction: column; gap: 1rem; }
            .form-group { display: flex; flex-direction: column; gap: 0.5rem; }
            label { font-weight: 600; color: var(--dark); }
            input[type="file"] { padding: 0.75rem; border: 2px solid #ddd; border-radius: 4px; transition: border-color 0.3s; }
            input[type="file"]:hover { border-color: var(--primary); }
            .radio-group { display: flex; flex-wrap: wrap; gap: 1rem; justify-content: flex-start; }
            .radio-group label { font-weight: normal; display: flex; align-items: center; gap: 0.5rem; }
            .select-group { display: flex; flex-direction: column; gap: 0.5rem; }
            select { padding: 0.75rem; border: 2px solid #ddd; border-radius: 4px; }
            button { background-color: var(--primary); color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 4px; font-size: 1rem; cursor: pointer; transition: background-color 0.3s; margin-top: 1rem; }
            button:hover { background-color: var(--secondary); }
            .file-info { margin-top: 1rem; padding: 1rem; background-color: var(--light); border-radius: 4px; display: none; }
            .progress-container { margin-top: 1rem; display: none; }
            progress { width: 100%; height: 1.5rem; border-radius: 4px; }
            .status { margin-top: 0.5rem; font-size: 0.875rem; text-align: center; }
            .error-message { color: var(--danger); padding: 1rem; background-color: #f8d7da; border-radius: 4px; margin-top: 1rem; display: none; }
            .warning-message { color: #856404; background-color: #fff3cd; padding: 1rem; border-radius: 4px; margin-top: 1rem; display: none; }
            .output-options { display: flex; flex-direction: column; gap: 1rem; margin-top: 1rem; }
            @media (max-width: 768px) { .container { margin: 1rem; padding: 1rem; } }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Versatile Data Report Generator</h1>
            <form id="uploadForm" class="upload-form" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="dataFile">Upload CSV or Excel (.xlsx) File</label>
                    <input type="file" id="dataFile" name="file" accept=".csv,.xlsx" required>
                </div>

                <div class="output-options">
                    <label>Choose Report Type:</label>
                    <div class="radio-group">
                        <label>
                            <input type="radio" name="report_type" value="summary" checked>
                            Summary
                        </label>
                        <label>
                            <input type="radio" name="report_type" value="full_data">
                            Full Data
                        </label>
                    </div>

                    <label>Choose Output Format:</label>
                    <div class="radio-group">
                        <label>
                            <input type="radio" name="output_format" value="pdf" checked>
                            PDF
                        </label>
                        <label>
                            <input type="radio" name="output_format" value="csv">
                            CSV
                        </label>
                        <label>
                            <input type="radio" name="output_format" value="excel">
                            Excel
                        </label>
                    </div>
                </div>

                <div class="select-group">
                    <label for="pageSize">Select Page Size for Full Data PDF</label>
                    <select id="pageSize" name="page_size" disabled>
                        <option value="A4">A4 (210 x 297 mm)</option>
                        <option value="A3">A3 (297 x 420 mm)</option>
                        <option value="A2">A2 (420 x 594 mm)</option>
                        <option value="A1">A1 (594 x 841 mm)</option>
                    </select>
                </div>
                <div class="warning-message" id="warningMessage">
                    <b>Warning:</b> Generating a "Full Data PDF" for large files will create a very large PDF and can take a long time. Consider using CSV or Excel output for speed.
                </div>
                <button type="submit" id="analyzeBtn">Analyze & Generate Report</button>
                <div class="file-info" id="fileInfo">
                    <strong>File:</strong> <span id="fileName"></span>
                    <div><strong>Size:</strong> <span id="fileSize"></span></div>
                </div>
                <div class="progress-container" id="progressContainer">
                    <progress id="analysisProgress" value="0" max="100"></progress>
                    <div class="status" id="statusMessage">Processing...</div>
                </div>
                <div class="error-message" id="errorMessage"></div>
            </form>
        </div>
        <script>
            document.getElementById('dataFile').addEventListener('change', function(e) {
                const file = e.target.files[0];
                if (file) {
                    document.getElementById('fileName').textContent = file.name;
                    document.getElementById('fileSize').textContent = (file.size / 1024 / 1024).toFixed(2) + ' MB';
                    document.getElementById('fileInfo').style.display = 'block';
                }
            });

            const reportTypeRadios = document.querySelectorAll('input[name="report_type"]');
            const outputFormatRadios = document.querySelectorAll('input[name="output_format"]');
            const pageSizeSelect = document.getElementById('pageSize');
            const warningBox = document.getElementById('warningMessage');

            function updateUIState() {
                const selectedReportType = document.querySelector('input[name="report_type"]:checked').value;
                const selectedOutputFormat = document.querySelector('input[name="output_format"]:checked').value;

                const isFullDataPDF = selectedReportType === 'full_data' && selectedOutputFormat === 'pdf';
                pageSizeSelect.disabled = !isFullDataPDF;
                warningBox.style.display = isFullDataPDF ? 'block' : 'none';
            }

            reportTypeRadios.forEach(radio => radio.addEventListener('change', updateUIState));
            outputFormatRadios.forEach(radio => radio.addEventListener('change', updateUIState));
            updateUIState(); // Initial state setup

            document.getElementById('uploadForm').addEventListener('submit', function(e) {
                e.preventDefault(); // Prevent default form submission

                const fileInput = document.getElementById('dataFile');
                const progressContainer = document.getElementById('progressContainer');
                const errorMessage = document.getElementById('errorMessage');

                if (!fileInput.files || fileInput.files.length === 0) {
                    errorMessage.textContent = 'Please select a file first.';
                    errorMessage.style.display = 'block';
                    return;
                }

                errorMessage.style.display = 'none';
                progressContainer.style.display = 'block';
                document.getElementById('analysisProgress').value = 0;
                document.getElementById('statusMessage').textContent = 'Uploading...';

                const formData = new FormData(this);

                fetch('/', {
                    method: 'POST',
                    body: formData
                })
                .then(response => {
                    if (response.ok) {
                        return response.blob().then(blob => {
                            const contentDisposition = response.headers.get('content-disposition');
                            let filename = 'report';
                            if (contentDisposition) {
                                const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
                                if (filenameMatch && filenameMatch[1]) {
                                    filename = decodeURIComponent(filenameMatch[1]);
                                }
                            }
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = filename;
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            document.body.removeChild(a);
                            progressContainer.style.display = 'none';
                            document.getElementById('statusMessage').textContent = 'Report generated successfully!';
                        });
                    } else {
                        return response.json().then(errorData => {
                            errorMessage.textContent = errorData.error || 'An unknown error occurred.';
                            errorMessage.style.display = 'block';
                            progressContainer.style.display = 'none';
                        }).catch(() => {
                            errorMessage.textContent = 'An unknown error occurred while processing the file.';
                            errorMessage.style.display = 'block';
                            progressContainer.style.display = 'none';
                        });
                    }
                })
                .catch(error => {
                    progressContainer.style.display = 'none';
                    errorMessage.textContent = 'Network error occurred.';
                    errorMessage.style.display = 'block';
                });
            });
        </script>
    </body>
    </html>
    ''')


if __name__ == '__main__':
    # Using a non-default port to avoid potential conflicts
    app.run(host='0.0.0.0', port=5000, debug=True)
