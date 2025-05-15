from app import PDF, sanitize_text
import os

def validate_pdf(file_path):
    """Validate that the PDF was created and has a reasonable size"""
    if not os.path.exists(file_path):
        return False, f"PDF file {file_path} was not created"
    
    file_size = os.path.getsize(file_path)
    if file_size < 1000:  # Less than 1KB
        return False, f"PDF file {file_path} is too small ({file_size} bytes)"
    if file_size > 1000000:  # More than 1MB
        return False, f"PDF file {file_path} is too large ({file_size} bytes)"
    
    return True, f"PDF file {file_path} was created successfully ({file_size} bytes)"

def generate_pdf(cv_text, output_file):
    """Generate a PDF from CV text"""
    pdf = PDF()
    pdf.add_page()
    pdf.format_cv(cv_text)
    
    try:
        pdf.output(output_file)
        success, message = validate_pdf(output_file)
        if success:
            print(f"✅ {message}")
        else:
            print(f"⚠️ {message}")
    except Exception as e:
        print(f"❌ Error generating {output_file}: {str(e)}")

def test_pdf_generation():
    # Test first CV format (Software Engineer)
    print("\nTesting first CV format (Software Engineer)...")
    with open('test_cv.txt', 'r') as f:
        cv1_text = f.read()
    generate_pdf(cv1_text, 'test_output_1.pdf')
    
    # Test second CV format (Data Scientist)
    print("\nTesting second CV format (Data Scientist)...")
    with open('test_cv_2.txt', 'r') as f:
        cv2_text = f.read()
    generate_pdf(cv2_text, 'test_output_2.pdf')
    
    # Test third CV format (Tech Leader)
    print("\nTesting third CV format (Tech Leader)...")
    with open('test_cv_3.txt', 'r') as f:
        cv3_text = f.read()
    generate_pdf(cv3_text, 'test_output_3.pdf')

if __name__ == "__main__":
    test_pdf_generation() 