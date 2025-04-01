from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import pytesseract
from PIL import Image
import spacy
import tempfile
import pdfplumber
from pdf2image import convert_from_path
from docx import Document
import re
from typing import Dict, Any
import os

app = FastAPI()
nlp = spacy.load("en_core_web_sm")

# Configure Tesseract (update path for your OS)
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # Linux/Mac
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Windows

@app.post("/analyze-file/")
async def analyze_file(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        try:
            # Save uploaded file temporarily
            contents = await file.read()
            temp_file.write(contents)
            temp_path = temp_file.name
            
            # Process based on file type
            file_ext = file.filename.split('.')[-1].lower()
            
            if file_ext in ["png", "jpg", "jpeg"]:
                text = extract_text_from_image(temp_path)
            elif file_ext == "pdf":
                text = extract_text_from_pdf(temp_path)
            elif file_ext == "txt":
                text = extract_text_from_txt(temp_path)
            elif file_ext == "docx":
                text = extract_text_from_docx(temp_path)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type")

            # Generate safe summary
            summary = generate_safe_summary(text)
            
            return JSONResponse(content=summary)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            temp_file.close()
            os.unlink(temp_path)

def extract_text_from_image(image_path: str) -> str:
    image = Image.open(image_path)
    return pytesseract.image_to_string(image)

def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        
        if not text.strip():
            images = convert_from_path(pdf_path)
            for img in images:
                text += pytesseract.image_to_string(img) + "\n"
    except Exception:
        text = "Could not extract PDF content"
    return text

def extract_text_from_txt(txt_path: str) -> str:
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read()

def extract_text_from_docx(docx_path: str) -> str:
    doc = Document(docx_path)
    return "\n".join(para.text for para in doc.paragraphs)

def generate_safe_summary(text: str) -> Dict[str, Any]:
    # Redact sensitive information
    redacted_text = re.sub(r'\+\d{2,}[\s\d-]+', '[PHONE]', text)
    redacted_text = re.sub(r'\S+@\S+', '[EMAIL]', redacted_text)
    redacted_text = re.sub(r'\b\d{4,}\b', '[NUMBERS]', redacted_text)  # Long numbers
    redacted_text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', redacted_text)
    
    # Analyze content
    doc = nlp(redacted_text)
    
    # Check for unsafe content
    unsafe_keywords = {
        "password", "ssn", "social security", 
        "credit card", "bank account", "confidential"
    }
    
    is_safe = True
    for token in doc:
        if token.text.lower() in unsafe_keywords:
            is_safe = False
            break
    
    # Generate summary
    summary = {
        "content_summary": "This appears to be a professional document" if is_safe else "Document contains sensitive content",
        "content_type": classify_content(redacted_text),
        "word_count": len(doc),
        "detected_entities": {
            "skills": extract_skills(doc),
            "organizations": extract_entities(doc, "ORG"),
            "dates": extract_entities(doc, "DATE")
        },
        "is_public_safe": is_safe,
        "privacy_notes": "Personal identifiers redacted" if is_safe else "Contains sensitive content - do not publish"
    }
    
    return summary

def classify_content(text: str) -> str:
    text_lower = text.lower()
    if "resume" in text_lower or "cv" in text_lower:
        return "Resume/CV"
    elif "contract" in text_lower or "agreement" in text_lower:
        return "Legal Document"
    elif "report" in text_lower or "analysis" in text_lower:
        return "Report"
    return "General Document"

def extract_skills(doc) -> list:
    skills = {"java", "python", "javascript", "html", "css", "php", "developer", "software"}
    return list(set(token.text for token in doc if token.text.lower() in skills))

def extract_entities(doc, entity_type: str) -> list:
    return list(set(ent.text for ent in doc.ents if ent.label_ == entity_type))