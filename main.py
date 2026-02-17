import streamlit as st
import cv2
import pandas as pd
import sqlite3
import time
import numpy as np
import os
import database as db
import config_manager as cm
import detector as det
import utils
import base64
# Configure Streamlit page layout
st.set_page_config(page_title="High-Performance Parking System",layout="wide")
# Session state to prevent rapid duplicate processing of the same plate
if 'last_processed' not in st.session_state:
    st.session_state['last_processed']=0
# Ensure directory for evidence photos exists
os.makedirs("captured_plates",exist_ok=True)
db.init_db()
def get_img_as_base64(file_path):
    # Encode local image to base64 string for HTML/Streamlit display
    with open(file_path,"rb") as f:
        data=f.read()
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
st.sidebar.title("Parking Management")
page=st.sidebar.radio("Navigate",["Dashboard","Settings","History"])
is_gpu,device_name=utils.check_gpu()
st.sidebar.success(f"Running on: {device_name}")
if page=="Dashboard":
    st.title("Real-Time AI Dashboard")
    # Top-level metric scorecards using placeholders for live updates
    col1,col2,col3=st.columns(3)
    m1=col1.empty()
    m2=col2.empty()
    m3=col3.empty()
    # Placeholder for the sidebar availability bars
    sidebar_placeholder=st.sidebar.empty()
    def refresh_metrics():
        # Update top metrics and sidebar bars simultaneously
        c_in,c_limit=db.get_free_spots('car')
        b_in,b_limit=db.get_free_spots('bike')
        c_empty=c_limit-c_in
        b_empty=b_limit-b_in
        m1.metric("Car Spaces Left",f"{c_empty}",f"{c_in} Occupied",delta_color="inverse")
        m2.metric("Bike Spaces Left",f"{b_empty}",f"{b_in} Occupied",delta_color="inverse")
        m3.metric("Today's Revenue",f"${db.get_total_revenue():.2f}")
        cm.render_sidebar_status(sidebar_placeholder)
    # Initial render
    refresh_metrics()
    st.markdown("---")
    source=st.radio("Select Input Source",["Image","Video","Webcam"],horizontal=True)
    col_video,col_stats=st.columns([0.7,0.3])
    with col_video:
        st.subheader("High-FPS Live Feed")
        frame_window=st.empty()
    with col_stats:
        st.subheader("System Activity")
        event_box=st.empty()
    cap=None
    stop_btn=False
    if source=="Image":
        up_file=st.file_uploader("Upload Image",type=['jpg','png','jpeg'])
        if up_file:
            file_bytes=np.asarray(bytearray(up_file.read()),dtype=np.uint8)
            frame=cv2.imdecode(file_bytes,1)
            processed_frame,data=det.detect_frame(frame)
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                img_path=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_path,processed_frame)
                status,msg,rec=db.handle_vehicle(data['text'],data['type'],img_path)
                refresh_metrics()
                if status=="Entry":
                    event_box.success(f"ENTRY: {data['text']}")
                elif status=="Exit":
                    event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}")
                else:event_box.error(msg)
    elif source=="Video":
        up_video=st.file_uploader("Upload Video",type=['mp4','webm'])
        if up_video:
            file_extension=up_video.name.split('.')[-1]
            temp_filename=f"temp.{file_extension}"
            with open(temp_filename,"wb") as f:
                f.write(up_video.read())
            cap=cv2.VideoCapture(temp_filename)
            stop_btn=st.button("Stop Video Processing")
    elif source=="Webcam":
        if st.button("Start Camera"):
            cap=cv2.VideoCapture(0)
            stop_btn=st.button("Stop Camera")
    # Video processing loop optimized for real-time performance
    if cap:
        while cap.isOpened():
            ret,frame=cap.read()
            if not ret or stop_btn:break
            processed_frame,data=det.detect_frame(frame)
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                current_time=time.time()
                # 4-second debounce to prevent multiple logs for the same vehicle detection
                if current_time-st.session_state['last_processed']>4:
                    img_filename=f"captured_plates/{data['text']}_{int(current_time)}.jpg"
                    cv2.imwrite(img_filename,processed_frame)
                    status,msg,rec=db.handle_vehicle(data['text'],data['type'],img_filename)
                    st.session_state['last_processed']=current_time
                    refresh_metrics() # Trigger live UI update
                    # Format timestamp with 2 decimal places for seconds
                    formatted_time=time.strftime('%H:%M:%S',time.localtime())+f".{int((time.time()%1)*100):02d}"
                    if status=="Entry":
                        event_box.success(f"ENTRY: {data['text']}\nTime: {formatted_time}")
                    elif status=="Exit":
                        event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}\nTime: {rec['time']:.2f} min")
                    else:event_box.error(msg)
        cap.release()
elif page=="Settings":
    cm.render_config_page()
elif page=="History":
    st.header("Financial & Parking Logs")
    conn=sqlite3.connect("parking.db")
    df_active=pd.read_sql_query("SELECT * FROM active_parking",conn)
    df_history=pd.read_sql_query("SELECT * FROM transaction_history ORDER BY id DESC",conn)
    search_query=st.text_input("Search License Plate",placeholder="Type plate number...").strip().upper()
    if search_query:
        df_active=df_active[df_active['plate_number'].str.contains(search_query,case=False,na=False)]
        df_history=df_history[df_history['plate_number'].str.contains(search_query,case=False,na=False)]
    # Convert local file paths to displayable Base64 images for History table
    if not df_active.empty:
        df_active['entry_time']=pd.to_datetime(df_active['entry_time']).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_active['evidence_img']=df_active['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    if not df_history.empty:
        for col in ['entry_time','exit_time']:
            df_history[col]=pd.to_datetime(df_history[col]).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_history['evidence_img']=df_history['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    col_refresh,col_download=st.columns([0.8,0.2])
    with col_refresh:
        if st.button("Refresh History"):st.rerun()
    with col_download:
        if not df_history.empty:
            csv_data=df_history.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV",csv_data,f"parking_report_{time.strftime('%Y%m%d')}.csv","text/csv")
    st.subheader("Live Parking Status")
    if df_active.empty and search_query:st.warning(f"No active vehicle found for '{search_query}'")
    else:
        st.data_editor(df_active,column_config={"evidence_img":st.column_config.ImageColumn("Evidence",help="Photo captured at entry"),"image_path":None,"plate_number":"License Plate","vehicle_type":"Type"},use_container_width=True,hide_index=True)
    st.markdown("---")
    st.subheader("Transaction History")
    if df_history.empty and search_query:st.warning(f"No history found for '{search_query}'")
    elif not df_history.empty:
        st.data_editor(df_history.style.format({"total_fee":"{:.2f}","duration_min":"{:.2f}"}),column_config={"evidence_img":st.column_config.ImageColumn("Entry Photo",help="Photo captured at entry"),"image_path":None,"plate_number":"License Plate","total_fee":st.column_config.NumberColumn("Fee ($)",format="$%.2f")},use_container_width=True,hide_index=True)
    if not df_history.empty:
        st.metric("Total Revenue (Filtered)",f"${df_history['total_fee'].sum():.2f}")
    conn.close()
#end
#python -m streamlit run main.py  (run in powershell)