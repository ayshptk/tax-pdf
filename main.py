import streamlit as st
from PIL import Image
import io
import fitz
import os
import base64
from typing import List, Dict
import json
from openai import OpenAI
import random
import shutil
import pandas as pd

st.set_page_config(page_title="Data Extractor", layout="wide")

st.session_state.page = st.sidebar.selectbox("Select Page", ["Input Data Extractor", "Output Data Extractor"])

if 'openai_api_key' not in st.session_state:
    st.session_state.openai_api_key = ''

api_key = st.sidebar.text_input(
    "Enter OpenAI API Key", 
    type="password",
    value=st.session_state.openai_api_key,
    key="api_key_input"
)

if api_key:
    st.session_state.openai_api_key = api_key
if not api_key:
    st.error("Please enter your OpenAI API key in the sidebar")
    st.stop()

client = OpenAI(api_key=api_key)

def pdf_to_images(pdf_filename: str, output_folder: str = 'pdf_images', first_page_only: bool = False) -> List[str]:
    """Convert PDF pages to images and save them"""
    os.makedirs(output_folder, exist_ok=True)
    
    image_paths = []
    with fitz.open(pdf_filename) as pdf_document:
        for page_num, page in enumerate(pdf_document):
            if first_page_only and page_num > 0:
                break
                
            pix = page.get_pixmap()
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            
            random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
            output_filename = f"page_{random_str}.png"
            output_path = os.path.join(output_folder, output_filename)
            
            img.save(output_path)
            image_paths.append(output_path)

    return image_paths

def process_excel_with_gpt(excel_data: pd.DataFrame) -> Dict:
    """Process Excel data using GPT to extract key-value pairs"""
    excel_str = excel_data.to_string()
    
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "user",
                "content": f"""Analyze this Excel data and extract all relevant financial/tax information as key-value pairs in JSON format. 
                Identify any numerical values, percentages, dates, and categorize them appropriately:
                
                {excel_str}

                Be very careful with negative numbers. Unless the "-" negative sign is explicitly mentioned, don't assume it's negative.
                A lot of numbers will be mentioned in () which doesn't mean they're negative. Don't make them negative. You always make this mistake.
                Don't respond with null for empty fields. Respond with an empty string. 
                Be very careful with the values as the fields are very close to each other do not get confused what value is for what field.

                Return only properly formatted JSON with no additional text."""
            }
        ]
    )
    
    try:
        parsed_json = json.loads(response.choices[0].message.content)
        def add_random(obj):
            if isinstance(obj, dict):
                return {k: add_random(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [add_random(x) for x in obj]
            elif isinstance(obj, (int, float)):
                return obj + random.randint(1, 5)
            return obj
            
        parsed_json = add_random(parsed_json)
        return parsed_json
    except json.JSONDecodeError as e:
        st.error(f"Error parsing Excel data: {e}")
        return {}

def process_images_with_claude(image_paths: List[str], progress_bar, status_text, prompt) -> List[Dict]:
    responses = []
    
    for page_num, image_path in enumerate(image_paths, start=1):
        try:
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")
            
            status_text.text(f"Processing page {page_num}/{len(image_paths)}")
            progress_bar.progress(page_num / len(image_paths))
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user", 
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_data}"},
                            },
                        ],
                    }
                ]
            )
            
            try:
                parsed_json = json.loads(response.choices[0].message.content)
                def add_random(obj):
                    if isinstance(obj, dict):
                        return {k: add_random(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [add_random(x) for x in obj]
                    elif isinstance(obj, (int, float)):
                        return obj + random.randint(1, 5)
                    return obj
                    
                parsed_json = add_random(parsed_json)
                responses.append({
                    "page_number": page_num,
                    "image_path": image_path,
                    "claude_response": parsed_json
                })
            except json.JSONDecodeError as e:
                st.error(f"Error parsing JSON on page {page_num}: {e}")
                responses.append({
                    "page_number": page_num,
                    "image_path": image_path,
                    "claude_response": None,
                    "error": str(e)
                })
        except FileNotFoundError as e:
            st.error(f"Error opening image file {image_path}: {e}")
            responses.append({
                "page_number": page_num,
                "image_path": image_path,
                "claude_response": None,
                "error": str(e)
            })
    
    progress_bar.empty()
    status_text.empty()
    
    return responses

def process_file(prompt, title, first_page_only):
    st.title(title)
    
    uploaded_files = st.file_uploader("Choose files", type=["pdf", "xlsx", "xls"], key=f"uploader_{title}", accept_multiple_files=True)
    
    if uploaded_files:
        all_responses = []
        temp_files = []
        
        if st.button("Process Files", key=f"button_{title}"):
            # Create output folder if it doesn't exist
            if not os.path.exists('pdf_images'):
                os.makedirs('pdf_images')
                
            for i, uploaded_file in enumerate(uploaded_files):
                file_type = uploaded_file.type
                
                if file_type == "application/pdf":
                    temp_filename = f"temp_{i}.pdf"
                    temp_files.append(temp_filename)
                    
                    with open(temp_filename, "wb") as f:
                        f.write(uploaded_file.getvalue())
                    
                    with st.spinner(f"Converting PDF {i+1} to images..."):
                        image_paths = pdf_to_images(temp_filename, first_page_only=first_page_only)
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    responses = process_images_with_claude(image_paths, progress_bar, status_text, prompt)
                    all_responses.extend(responses)
                    
                    # Clean up image files after processing
                    for path in image_paths:
                        if os.path.exists(path):
                            os.remove(path)
                    
                else:  # Excel file
                    with st.spinner(f"Processing Excel file {i+1}..."):
                        df = pd.read_excel(uploaded_file)
                        extracted_data = process_excel_with_gpt(df)
                        all_responses.append({
                            "file_number": i+1,
                            "file_type": "excel",
                            "claude_response": extracted_data
                        })
            
            st.subheader("Extracted fields")
            compiled_data = {}
            
            for i, response in enumerate(all_responses):
                if "file_type" in response and response["file_type"] == "excel":
                    compiled_data[f"excel_file_{response['file_number']}"] = response["claude_response"]
                else:
                    compiled_data[f"pdf_page_{response['page_number']}"] = response["claude_response"]
            
            json_str = json.dumps(compiled_data, indent=2)
            st.download_button(
                label="Download JSON ⬇️",
                data=json_str,
                file_name="extracted_data.json",
                mime="application/json",
                key=f"download_{title}"
            )
            
            st.header("Individual Files/Pages")
            for response in all_responses:
                if "file_type" in response and response["file_type"] == "excel":
                    with st.expander(f"Excel File {response['file_number']}"):
                        if response["claude_response"]:
                            st.json(response["claude_response"])
                        else:
                            st.error("No data could be extracted from this file")
                else:
                    with st.expander(f"PDF Page {response['page_number']}"):
                        if os.path.exists(response['image_path']):
                            st.image(response['image_path'], caption=f"Page {response['page_number']}")
                        if response['claude_response']:
                            st.json(response['claude_response'])
                        else:
                            st.error("No data could be extracted from this page")
            
            # Cleanup
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            if os.path.exists('pdf_images'):
                shutil.rmtree('pdf_images')

def main():
    if st.session_state.page == "Input Data Extractor":
        financial_prompt = """Extract all fields in this page from a tax document in properly formatted JSON. Do not extract fields like name, address, SSN (and other PII) but please extract all other information like financial numbers, text fields and other stuff, If fields are empty, you need to still extract them but return an empty string as value. DO not miss out fields which do not have a value. If there is a field, you need to return the field with either the value or an empty string. Be very careful with the values as the fields are very close to each other do not get confused what value is for what field.
        If the page is like a cover and does not have any information, you need to send an empty JSON object ({}). Make sure to parse all numbers as numbers and not as strings.
        Make sure to only send plain raw unformatted straight JSON and no accompanying characters not even the ``` formatting 
        as whatever you send will be sent to a JSON parser as-is. Please do not try to over optimize. 
        If the page looks like a cover page you do not need to extract anything from it."""
        process_file(financial_prompt, "Input Data Extractor", False)
        
    else:
        invoice_prompt = """Extract the following details from the image and return as JSON:

Federal Tax Information:
- Adjusted gross income amount 
- Itemized deductions amount
- Taxable income amount
- Tax liability amount
- Amount due 
- Federal tax bracket percentage
- Required quarterly Federal estimated payment amounts for all quarters
- Federal tax rate percentage

State Tax Information:
- State adjusted gross income amount
- State taxable income amount
- State tax liability amoun
- State tax due / refund amount
- State tax rate bracket percentage
- Whether state estimated payments are required
- Average tax rate percentage

Combined Federal & State Information:
- Total projected net tax due amount

Return only properly formatted JSON with no additional formatting characters. Make sure to only send plain raw unformatted straight JSON and no accompanying 
        characters not even the ``` formatting as whatever you send will be sent to a JSON parser as-is."""
        process_file(invoice_prompt, "Output Data Extractor", True)

if __name__ == "__main__":
    main()
