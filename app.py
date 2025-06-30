from flask import Flask, request, send_file, jsonify
import subprocess
import os
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow requests from any origin (frontend on Vercel)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return "✅ Scrapo Backend Running"

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        # Handle scraping from URL
        if 'url' in request.form:
            url = request.form['url']
            output_file = os.path.join(UPLOAD_FOLDER, f'output_{os.getpid()}.csv')
            result = subprocess.run(['python', 'web.py', url, output_file], capture_output=True)

            if result.returncode != 0:
                return jsonify({'error': 'Scraping failed', 'details': result.stderr.decode()}), 500

            return send_file(output_file, as_attachment=True)

        # Handle scraping from uploaded file
        elif 'file' in request.files:
            file = request.files['file']
            filename = secure_filename(file.filename)
            input_path = os.path.join(UPLOAD_FOLDER, filename)
            output_path = os.path.join(UPLOAD_FOLDER, f"{filename}_output.csv")

            file.save(input_path)
            result = subprocess.run(['python', 'process.py', input_path, output_path], capture_output=True)

            if result.returncode != 0:
                return jsonify({'error': 'Processing failed', 'details': result.stderr.decode()}), 500

            return send_file(output_path, as_attachment=True)

        else:
            return jsonify({'error': 'No URL or file provided'}), 400

    except Exception as e:
        return jsonify({'error': 'Unexpected error', 'details': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
