import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import os
from pathlib import Path
import pdfplumber
import docx
from io import BytesIO
import json
from fpdf import FPDF
from datetime import datetime
import sqlite3
from typing import Union
from werkzeug.utils import secure_filename
import time

# Load environment variables
load_dotenv()

# Configure OpenAI with the new client
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
)

# Prompts for CV processing
STRUCTURE_PROMPT = """
你是一个专业的英文简历撰写专家。请将以下中文简历内容翻译成英文，并按照以下 JSON 格式输出：
{
  "full_name": "张三",
  "email": "zhangsan@example.com",
  "phone": "+86 138 0000 0000",
  "education": [
    {"degree": "Bachelor of Engineering", "university": "Tsinghua University", "year": "2022"}
  ],
  "experience": [
    {"title": "Software Engineer", "company": "Tencent", "dates": "2022 - Present", "bullets": ["Developed backend systems using Go.", "Improved latency by 30%."]}
  ],
  "skills": ["Python", "SQL", "TensorFlow"]
}

中文简历如下：
{cv_text}
"""

POLISH_PROMPT = """
You are a professional English CV editor. Please polish the following English CV content. Keep the structure, but improve grammar, clarity, and impact. Respond with the result in the same format:

{cv_text}
"""

SCORE_PROMPT = """
You are a professional resume reviewer. Please score the following English CV content from 1 to 10 based on professionalism, clarity, grammar, and impact. Then provide a short paragraph explaining the score and areas to improve. Format:

Score: x/10
Feedback: ...

CV:
{cv_text}
"""

# Helper Functions
def extract_text_from_pdf(uploaded_file):
    """Extract text from PDF file"""
    text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def extract_text_from_docx(uploaded_file):
    """Extract text from DOCX file"""
    doc = docx.Document(uploaded_file)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

def is_chinese(text):
    """Detect if text is primarily Chinese"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_chars / max(len(text), 1) > 0.3

def call_openai_prompt(prompt):
    """Call OpenAI API with the new client"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Error calling OpenAI API: {str(e)}")
        return None

def sanitize_text(text):
    """Clean up text for PDF rendering"""
    if not isinstance(text, str):
        text = str(text)
    
    # Replace bullet points and similar characters
    text = text.replace('•', '*')
    text = text.replace('·', '*')
    text = text.replace('○', '*')
    text = text.replace('◦', '*')
    text = text.replace('→', '->')
    text = text.replace('—', '-')
    text = text.replace('–', '-')
    
    # Replace problematic whitespace characters
    text = text.replace('\u00a0', ' ')  # non-breaking space
    text = text.replace('\u200b', '')   # zero-width space
    text = text.replace('\u200c', '')   # zero-width non-joiner
    text = text.replace('\u200d', '')   # zero-width joiner
    text = text.replace('\u202f', ' ')  # narrow non-breaking space
    text = text.replace('\ufeff', '')   # byte order mark
    
    # Replace line separators with newlines
    text = text.replace('\u2028', '\n')  # line separator
    text = text.replace('\u2029', '\n')  # paragraph separator
    
    # Clean up multiple spaces and lines
    text = ' '.join(text.split())  # Replace multiple spaces with single space
    
    return text

class Lead:
    def __init__(self, db_path="cv_optimizer.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    cv_score INTEGER,
                    submission_date DATETIME,
                    contacted BOOLEAN DEFAULT FALSE
                )
            """)

    def add_lead(self, email: str, cv_score: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO leads (email, cv_score, submission_date) VALUES (?, ?, ?)",
                (email, cv_score, datetime.now())
            )

class PDF(FPDF):
    def __init__(self):
        super().__init__()
        # A4 format with smaller margins
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=15)
        self.section_spacing = 10
        self.line_height = 6
        self.bullet_char = "-"  # Use ASCII character for bullet point
        
        # Colors
        self.header_bg_color = (41, 128, 185)  # Blue
        self.header_text_color = (255, 255, 255)  # White
        self.section_line_color = (220, 220, 220)  # Light gray
        self.label_color = (100, 100, 100)  # Dark gray for labels
        self.link_color = (41, 128, 185)  # Blue for links and company names
        
        self.section_markers = [
            'PERSONAL INFORMATION',
            'PROFESSIONAL SUMMARY',
            'EDUCATION',
            'EXPERIENCE',
            'PROFESSIONAL EXPERIENCE',
            'SKILLS',
            'TECHNICAL SKILLS',
            'PROJECTS',
            'PUBLICATIONS',
            'SELECTED PUBLICATIONS & PATENTS',
            'CERTIFICATIONS',
            'AWARDS & HONORS',
            'LANGUAGES'
        ]

    def header(self):
        # Blue header background
        self.set_fill_color(*self.header_bg_color)
        self.rect(0, 0, self.w, 40, 'F')
        
        # White text for header
        self.set_text_color(*self.header_text_color)
        self.set_font('Helvetica', 'B', 20)
        self.cell(0, 25, 'CV Optimization Report', 0, 1, 'C')
        self.ln(20)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Generated by CV Optimizer Pro | {datetime.now().strftime("%Y-%m-%d %H:%M")}', 0, 0, 'C')

    def add_section_title(self, title):
        """Add a section title with simple bold text and underline"""
        # Add some space before section
        self.ln(5)
        
        # Section title in bold black
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(0, 0, 0)  # Black text
        self.cell(0, 10, title.upper(), 0, 1, 'L', False)  # Removed fill
        
        # Add separator line
        self.ln(1)
        self.set_draw_color(*self.section_line_color)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)

    def add_personal_info_item(self, label, value):
        """Add a personal information item with aligned label and value"""
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(*self.label_color)
        
        # Calculate label width (fixed for alignment)
        label_width = 40
        self.cell(label_width, self.line_height, label + ":", 0, 0, 'L')
        
        # Value in normal text
        self.set_font('Helvetica', '', 11)
        self.set_text_color(0, 0, 0)
        self.cell(0, self.line_height, value, 0, 1, 'L')

    def add_experience(self, role_company, company, dates, description):
        """Format an experience entry with improved styling"""
        # Split role and company if combined
        if ' - ' in role_company:
            role, company = role_company.split(' - ', 1)
        elif ' at ' in role_company.lower():
            role, company = role_company.split(' at ', 1)
        elif '|' in role_company:
            role, company = role_company.split('|', 1)
        else:
            role = role_company
        
        # Clean up
        role = role.strip()
        company = company.strip()
        
        # Add subtle separator line before each experience (except first)
        if self.get_y() > 50:  # Don't add line if it's the first item
            self.set_draw_color(*self.section_line_color)
            self.line(self.l_margin + 10, self.get_y() - 2, self.w - self.r_margin - 10, self.get_y() - 2)
            self.ln(4)
        
        # Role in bold black
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(0, 0, 0)
        self.add_wrapped_text(role)
        
        # Company in blue
        self.set_font('Helvetica', '', 11)
        self.set_text_color(*self.link_color)
        self.add_wrapped_text(company)
        
        # Dates in gray italic
        self.set_font('Helvetica', 'I', 10)
        self.set_text_color(*self.label_color)
        self.add_wrapped_text(dates)
        
        self.ln(2)  # Space before bullets
        
        # Description with bullet points
        for point in description.split('\n'):
            if point.strip():
                if point.strip().startswith(('•', '-', '*')):
                    self.add_bullet_point(point.strip()[1:].strip())
                else:
                    self.add_wrapped_text(point.strip())
        
        self.ln(8)  # Space between experiences

    def format_cv(self, cv_text):
        """Format the CV with improved layout"""
        sections = self.parse_cv_sections(cv_text)
        
        # Personal Information with aligned labels
        if 'PERSONAL INFORMATION' in sections:
            self.add_section_title('Personal Information')
            info_lines = sections['PERSONAL INFORMATION'].split('\n')
            for line in info_lines:
                if ':' in line:
                    label, value = line.split(':', 1)
                    self.add_personal_info_item(label.strip(), value.strip())
                else:
                    self.set_font('Helvetica', '', 11)
                    self.add_wrapped_text(line)
            self.ln(self.section_spacing)

        # Professional Summary
        if 'PROFESSIONAL SUMMARY' in sections:
            self.add_section_title('Professional Summary')
            self.add_wrapped_text(sections['PROFESSIONAL SUMMARY'])
            self.ln(self.section_spacing)

        # Education
        if 'EDUCATION' in sections:
            self.add_section_title('Education')
            edu_entries = sections['EDUCATION'].split('\n\n')
            for entry in edu_entries:
                if entry.strip():
                    lines = [line.strip() for line in entry.split('\n') if line.strip()]
                    if lines:
                        # First line should contain degree and year
                        self.set_font('Helvetica', 'B', 11)
                        self.add_wrapped_text(lines[0])
                        
                        # Second line should be institution
                        if len(lines) > 1:
                            self.set_font('Helvetica', '', 11)
                            self.set_text_color(41, 128, 185)
                            self.add_wrapped_text(lines[1])
                            self.set_text_color(0, 0, 0)
                        
                        # Additional lines as bullet points or regular text
                        for line in lines[2:]:
                            if line.strip().startswith(('*', '•', '-')):
                                self.add_bullet_point(line.strip()[1:].strip())
                            else:
                                self.set_font('Helvetica', '', 11)
                                self.add_wrapped_text(line)
                    self.ln(5)
            self.ln(self.section_spacing)

        # Experience sections
        exp_sections = ['EXPERIENCE', 'PROFESSIONAL EXPERIENCE']
        for section in exp_sections:
            if section in sections:
                self.add_section_title('Professional Experience')
                exp_entries = sections[section].split('\n\n')
                for entry in exp_entries:
                    if entry.strip():
                        lines = [line.strip() for line in entry.split('\n') if line.strip()]
                        if len(lines) >= 2:
                            # Parse role and company
                            role_line = lines[0]
                            if '|' in role_line:
                                role, company = role_line.split('|', 1)
                            else:
                                role, company = role_line, ''
                            
                            # Get location and dates
                            dates_loc = lines[1]
                            
                            # Description starts from third line
                            description = '\n'.join(lines[2:])
                            
                            # Add the experience entry
                            self.add_experience(role.strip(), company.strip(), dates_loc, description)
                self.ln(self.section_spacing)

        # Skills section with subsections
        if 'TECHNICAL SKILLS' in sections or 'SKILLS' in sections:
            self.add_section_title('Technical Skills')
            skills_text = sections.get('TECHNICAL SKILLS', sections.get('SKILLS', ''))
            current_category = None
            
            for line in skills_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                if line.endswith(':'):
                    # This is a category
                    current_category = line.rstrip(':')
                    self.set_font('Helvetica', 'B', 11)
                    self.set_text_color(41, 128, 185)
                    self.add_wrapped_text(current_category)
                    self.set_text_color(0, 0, 0)
                elif line.startswith(('*', '•', '-')):
                    self.add_bullet_point(line[1:].strip())
                else:
                    self.set_font('Helvetica', '', 11)
                    self.add_wrapped_text(line)
            self.ln(self.section_spacing)

        # Other sections
        other_sections = ['PROJECTS', 'PUBLICATIONS', 'SELECTED PUBLICATIONS & PATENTS',
                         'CERTIFICATIONS', 'AWARDS & HONORS', 'LANGUAGES']
        for section in other_sections:
            if section in sections:
                self.add_section_title(section)
                lines = sections[section].split('\n')
                current_subsection = None
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.endswith(':'):
                        # This is a subsection
                        current_subsection = line
                        self.set_font('Helvetica', 'B', 11)
                        self.add_wrapped_text(current_subsection)
                    elif line.startswith(('*', '•', '-')):
                        self.add_bullet_point(line[1:].strip())
                    else:
                        self.set_font('Helvetica', '', 11)
                        self.add_wrapped_text(line)
                self.ln(self.section_spacing)

    def parse_cv_sections(self, cv_text):
        """Parse CV text into sections"""
        sections = {}
        current_section = None
        current_content = []
        
        # Split text into lines and process
        lines = cv_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if line is a section header
            upper_line = line.upper()
            is_section = False
            
            # Check if line matches any section marker
            for marker in self.section_markers:
                if marker in upper_line or upper_line in marker:
                    if current_section:
                        sections[current_section] = '\n'.join(current_content)
                    current_section = marker
                    current_content = []
                    is_section = True
                    break
            
            # If not a section header, add to current content
            if not is_section:
                if current_section:
                    current_content.append(line)
                else:
                    # If no section yet, assume it's personal information
                    current_section = 'PERSONAL INFORMATION'
                    current_content.append(line)
        
        # Add the last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content)
            
        return sections

    def add_wrapped_text(self, text, font_family='Helvetica', style='', size=11, color=(0,0,0)):
        """Helper method to add text with proper wrapping"""
        self.set_font(font_family, style, size)
        self.set_text_color(*color)
        text = sanitize_text(text)
        
        # Split text into words and add them one by one
        words = text.split()
        line = []
        x_start = self.get_x()
        
        for word in words:
            # Test if adding this word would exceed the width
            test_line = ' '.join(line + [word])
            test_width = self.get_string_width(test_line)
            
            if test_width > (self.w - self.r_margin - self.l_margin):
                # Print current line and start a new one
                if line:
                    self.cell(0, self.line_height, ' '.join(line), ln=1)
                    line = [word]
                else:
                    # Word is too long for the line, need to hyphenate
                    self.cell(0, self.line_height, word, ln=1)
            else:
                line.append(word)
        
        # Print the last line
        if line:
            self.cell(0, self.line_height, ' '.join(line), ln=1)

    def add_bullet_point(self, text, indent=5):
        """Add a bullet point with improved styling"""
        text = sanitize_text(text)
        self.set_font('Helvetica', '', 11)
        self.set_text_color(0, 0, 0)
        
        # Save current position
        start_x = self.get_x()
        
        # Add bullet point with ASCII character
        self.cell(indent, self.line_height, "", 0, 0, 'L')  # Indent
        self.set_text_color(*self.link_color)  # Bullet in accent color
        self.cell(3, self.line_height, self.bullet_char, 0, 0, 'L')  # Bullet point
        self.set_text_color(0, 0, 0)  # Reset text color
        
        # Calculate available width for text
        available_width = self.w - self.r_margin - (start_x + indent + 5)
        
        # Split text into words and add them with proper wrapping
        words = text.split()
        line = []
        
        for word in words:
            # Test if adding this word would exceed the width
            test_line = ' '.join(line + [word])
            test_width = self.get_string_width(test_line)
            
            if test_width > available_width:
                # Print current line and start a new one
                if line:
                    self.set_x(start_x + indent + 5)
                    self.cell(available_width, self.line_height, ' '.join(line), 0, 1, 'L')
                    line = [word]
                else:
                    # Word is too long for the line, need to hyphenate
                    self.set_x(start_x + indent + 5)
                    self.cell(available_width, self.line_height, word, 0, 1, 'L')
            else:
                line.append(word)
        
        # Print the last line
        if line:
            self.set_x(start_x + indent + 5)
            self.cell(available_width, self.line_height, ' '.join(line), 0, 1, 'L')
        
        self.ln(1)  # Small space after bullet point

class UIComponents:
    @staticmethod
    def show_processing_progress():
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        stages = [
            "Extracting text...",
            "Processing content...",
            "Analyzing format...",
            "Generating output..."
        ]
        
        for i, stage in enumerate(stages):
            status_text.text(stage)
            progress_bar.progress((i + 1) * 25)
            time.sleep(0.5)
        
        progress_bar.empty()
        status_text.empty()

def main():
    # Page configuration
    st.set_page_config(
        page_title="CV Optimizer Pro",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    # Custom CSS for sleek design
    st.markdown("""
        <style>
        .stApp {
            background-color: #ffffff;
        }
        .main-title {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: #1E88E5;
        }
        .subtitle {
            font-size: 1.1rem;
            color: #424242;
            margin-bottom: 1rem;
        }
        .feature-box {
            background-color: #f8f9fa;
            padding: 1.2rem;
            border-radius: 4px;
            margin: 1rem 0;
        }
        .feature-title {
            color: #1E88E5;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        .feature-text {
            color: #424242;
            font-size: 0.95rem;
            margin-bottom: 0.5rem;
        }
        .stButton > button {
            width: 100%;
            background-color: #1E88E5;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 4px;
        }
        .stButton > button:hover {
            background-color: #1976D2;
        }
        .results-container {
            background-color: #f8f9fa;
            padding: 1.5rem;
            border-radius: 4px;
            margin: 1rem 0;
        }
        .intro-text {
            color: #424242;
            font-size: 1.05rem;
            line-height: 1.6;
            margin-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown('<p class="main-title">📄 CV Optimizer Pro</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Transform your CV with AI-powered optimization</p>', unsafe_allow_html=True)

    # Introduction
    st.markdown("""
        <p class="intro-text">
        Welcome to CV Optimizer Pro, your intelligent assistant for creating professional, impactful CVs. 
        Our AI-powered platform helps you transform your CV by enhancing content, improving language, 
        and ensuring professional formatting.
        </p>
    """, unsafe_allow_html=True)

    # Key Features Section
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
            <div class="feature-box">
                <p class="feature-title">🤖 AI-Powered Enhancement</p>
                <p class="feature-text">• Improves clarity and impact</p>
                <p class="feature-text">• Enhances professional language</p>
                <p class="feature-text">• Optimizes content structure</p>
            </div>
            <div class="feature-box">
                <p class="feature-title">📊 Professional Scoring</p>
                <p class="feature-text">• Detailed CV evaluation</p>
                <p class="feature-text">• Actionable feedback</p>
                <p class="feature-text">• Industry-standard metrics</p>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
            <div class="feature-box">
                <p class="feature-title">🌏 Bilingual Support</p>
                <p class="feature-text">• English and Chinese support</p>
                <p class="feature-text">• Professional translation</p>
                <p class="feature-text">• Cultural adaptation</p>
            </div>
            <div class="feature-box">
                <p class="feature-title">📝 Smart Formatting</p>
                <p class="feature-text">• Clean, modern layout</p>
                <p class="feature-text">• ATS-friendly format</p>
                <p class="feature-text">• Multiple export options</p>
            </div>
        """, unsafe_allow_html=True)

    # How it works
    st.markdown("""
        <p class="feature-title" style="margin-top: 2rem;">How It Works:</p>
        <p class="feature-text">1. Upload your CV in PDF or Word format</p>
        <p class="feature-text">2. Our AI analyzes and enhances your content</p>
        <p class="feature-text">3. Review improvements and feedback</p>
        <p class="feature-text">4. Download your optimized CV</p>
    """, unsafe_allow_html=True)

    # File upload section
    st.markdown('<div style="margin-top: 2rem;">', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Upload your CV (PDF or Word)", type=["pdf", "docx"])
    
    if uploaded_file is not None:
        with st.spinner("Extracting content..."):
            if uploaded_file.name.endswith(".pdf"):
                raw_text = extract_text_from_pdf(uploaded_file)
            else:
                raw_text = extract_text_from_docx(uploaded_file)

        if raw_text.strip():
            # Show progress
            ui = UIComponents()
            ui.show_processing_progress()

            if is_chinese(raw_text):
                with st.spinner("Detected Chinese CV, translating and formatting..."):
                    prompt = STRUCTURE_PROMPT.replace("{cv_text}", raw_text)
                    content = call_openai_prompt(prompt)
                    try:
                        structured_data = json.loads(content)
                        
                        st.markdown('<div class="results-container">', unsafe_allow_html=True)
                        st.subheader("🎯 Translated and Structured CV")
                        st.json(structured_data)
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        # Generate PDF
                        pdf = PDF()
                        pdf.add_page()
                        pdf.format_cv(json.dumps(structured_data, indent=2))
                        pdf_output = BytesIO()
                        pdf.output(pdf_output)
                        
                        # Download section
                        st.subheader("⬇️ Download Options")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(
                                label="Download PDF CV",
                                data=pdf_output.getvalue(),
                                file_name="Translated_CV.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                        with col2:
                            st.download_button(
                                label="Download JSON Data",
                                data=json.dumps(structured_data, indent=2),
                                file_name="cv_data.json",
                                mime="application/json",
                                use_container_width=True
                            )
                    except json.JSONDecodeError:
                        st.error("⚠️ Error in JSON formatting")
                        st.text_area("Raw output:", content, height=400)
            else:
                with st.spinner("Processing English CV..."):
                    # Polish the CV
                    prompt = POLISH_PROMPT.replace("{cv_text}", raw_text)
                    polished = call_openai_prompt(prompt)
                    
                    # Generate PDF
                    pdf = PDF()
                    pdf.add_page()
                    pdf.format_cv(polished)
                    pdf_output = BytesIO()
                    pdf.output(pdf_output)
                    
                    # Score the CV
                    score_result = call_openai_prompt(SCORE_PROMPT.replace("{cv_text}", polished))
                    
                    # Display results in clean sections
                    st.markdown('<div class="results-container">', unsafe_allow_html=True)
                    st.subheader("📝 Enhanced CV")
                    st.text_area("", polished, height=300)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="results-container">', unsafe_allow_html=True)
                    st.subheader("📊 CV Score and Feedback")
                    st.text_area("", score_result, height=150)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    # Download section
                    st.subheader("⬇️ Download Options")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            label="Download PDF CV",
                            data=pdf_output.getvalue(),
                            file_name="Enhanced_CV.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    with col2:
                        st.download_button(
                            label="Download Text CV",
                            data=polished.encode("utf-8"),
                            file_name="Enhanced_CV.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
                    
                    # Lead collection for low scores
                    if "Score: " in score_result:
                        try:
                            score_line = [line for line in score_result.splitlines() if "Score:" in line][0]
                            score = int(score_line.split(":")[1].split("/")[0].strip())
                            if score < 7:
                                st.markdown("---")
                                st.warning("🎯 Your CV score is below 7/10. Consider our professional CV review service!")
                                with st.expander("Get Professional Help"):
                                    st.markdown("#### 📬 Leave your email for a personalized CV improvement consultation")
                                    user_email = st.text_input("Email address")
                                    if user_email:
                                        lead = Lead()
                                        lead.add_lead(user_email, score)
                                        st.success(f"Thank you! We'll contact you within 24 hours at: {user_email}")
                        except:
                            pass
        else:
            st.error("Could not extract text from the file.")

    # Footer
    st.markdown("""
        <div style="text-align: center; margin-top: 3rem; padding: 1rem; color: #666;">
            <p>Made with ❤️ by CV Optimizer Pro</p>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main() 