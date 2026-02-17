import cv2
import numpy as np
from ultralytics import YOLO
import easyocr
import torch
model=None
reader=None
def load_models():
    global model,reader
    if model is None:
        model=YOLO('yolov8n.pt')
    if reader is None:
        gpu_available=torch.cuda.is_available()
        reader=easyocr.Reader(['en'],gpu=gpu_available)
    return model,reader
def detect_frame(frame,conf_thresh=0.45):
    model_inst,reader_inst=load_models()
    # Detect vehicles: 2=Car, 3=Motorcycle, 5=Bus, 7=Truck
    results=model_inst(frame,classes=[2,3,5,7],conf=conf_thresh,verbose=False)
    annotated_frame=frame.copy()
    detection_data=None 
    for r in results:
        for box in r.boxes:
            x1,y1,x2,y2=map(int,box.xyxy[0])
            cls_id=int(box.cls[0])
            # Map YOLO motorcycle (3) to our 'bike' type
            if cls_id==3:
                v_type="bike"
                color=(0,255,255) # Yellow
                label_text="BIKE"
            else:
                v_type="car"
                color=(0,255,0) # Green
                label_text="CAR"
            # Draw vehicle bounding box
            cv2.rectangle(annotated_frame,(x1,y1),(x2,y2),color,2)
            cv2.putText(annotated_frame,label_text,(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,color,1)
            # Expand search area for vertical/two-row plates
            h=y2-y1
            plate_y1=y1+int(h*0.3) 
            roi=frame[plate_y1:y2,x1:x2]
            if roi.size>0:
                # OCR restricted to uppercase alphanumeric
                ocr_results=reader_inst.readtext(roi,allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
                plate_texts=[]
                # Collect all text blocks found in the plate area
                for _,text,conf in ocr_results:
                    if conf>0.3:
                        plate_texts.append(text.replace(" ","").upper())
                # If we found text, join it (e.g., 'AP39S' + '8889' = 'AP39S8889')
                if plate_texts:
                    full_plate="".join(plate_texts)
                    # Filter for minimum length to avoid noise
                    if len(full_plate)>4:
                        detection_data={'text':full_plate,'type':v_type,'conf':0.99}
                        cv2.putText(annotated_frame,f"PLATE: {full_plate}",(x1,y2+25),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2)
                        return annotated_frame,detection_data
    # Always return the frame for the video stream
    return annotated_frame,None