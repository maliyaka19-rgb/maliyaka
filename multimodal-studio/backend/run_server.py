import sys
import os
os.chdir(r"C:\Users\HP\Desktop\YAPAY ZEKA\multimodal-studio\backend")
import uvicorn
uvicorn.run("app:app", host="0.0.0.0", port=8000)