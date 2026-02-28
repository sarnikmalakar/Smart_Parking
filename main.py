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
st.set_page_config(page_title="High-Performance Parking System",layout="wide")
# setup our set cache to store tracked ByteTrack IDs during the active session
if 'processed_tracks' not in st.session_state:st.session_state['processed_tracks']=set()
os.makedirs("captured_plates",exist_ok=True)
db.init_db()
def get_img_as_base64(file_path):
    with open(file_path,"rb") as f:data=f.read()
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
st.sidebar.title("Parking Management")
page=st.sidebar.radio("Navigate",["Dashboard","Settings","History","Security","Analytics"])
is_gpu,device_name=utils.check_gpu()
st.sidebar.success(f"Running on: {device_name}")
if page=="Dashboard":
    st.title("Real-Time AI Dashboard")
    col1,col2,col3=st.columns(3)
    m1,m2,m3=col1.empty(),col2.empty(),col3.empty()
    sidebar_placeholder=st.sidebar.empty()
    def refresh_metrics():
        c_in,c_limit=db.get_free_spots('car')
        b_in,b_limit=db.get_free_spots('bike')
        m1.metric("Car Spaces Left",f"{c_limit-c_in}",f"{c_in} Occupied",delta_color="inverse")
        m2.metric("Bike Spaces Left",f"{b_limit-b_in}",f"{b_in} Occupied",delta_color="inverse")
        m3.metric("Today's Revenue",f"${db.get_total_revenue():.2f}")
        cm.render_sidebar_status(sidebar_placeholder)
    refresh_metrics()
    st.markdown("---")
    # Multi-Gate Architecture Setup
    c_src,c_gate=st.columns(2)
    with c_src:source=st.radio("Select Input Source",["Image","Video","Webcam"],horizontal=True)
    with c_gate:gate_type=st.radio("Gate Role",["Entry Gate","Exit Gate","Auto (Combined)"],horizontal=True)
    gate_mode=gate_type.split()[0] # pulls Entry, Exit, or Auto
    col_video,col_stats=st.columns([0.7,0.3])
    with col_video:
        st.subheader(f"Live Feed: {gate_type}")
        frame_window=st.empty()
    with col_stats:
        st.subheader("System Activity")
        event_box=st.empty()
    cap,stop_btn=None,False
    if source=="Image":
        up_file=st.file_uploader("Upload Image",type=['jpg','png','jpeg'])
        if up_file:
            file_bytes=np.asarray(bytearray(up_file.read()),dtype=np.uint8)
            frame=cv2.imdecode(file_bytes,1)
            # pass empty set for single images since tracking isn't continuous here
            processed_frame,data=det.detect_frame(frame,set())
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                img_path=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_path,processed_frame)
                status,msg,rec=db.handle_vehicle(data['text'],data['type'],img_path,gate_mode)
                refresh_metrics()
                if status=="Entry":event_box.success(f"ENTRY: {data['text']}")
                elif status=="Exit":event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}")
                else:event_box.error(msg)
    elif source=="Video":
        up_video=st.file_uploader("Upload Video",type=['mp4','webm'])
        if up_video:
            ext=up_video.name.split('.')[-1]
            with open(f"temp.{ext}","wb") as f:f.write(up_video.read())
            cap=cv2.VideoCapture(f"temp.{ext}")
            stop_btn=st.button("Stop Video Processing")
    elif source=="Webcam":
        if st.button("Start Camera"):
            cap=cv2.VideoCapture(0)
            stop_btn=st.button("Stop Camera")
    if cap:
        while cap.isOpened():
            ret,frame=cap.read()
            if not ret or stop_btn:break
            # send our processed_tracks state to detector to skip redundant OCRs
            processed_frame,data=det.detect_frame(frame,st.session_state['processed_tracks'])
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                special_info=db.get_special_plate(data['text'])
                is_blacklisted=special_info and special_info[0]=='Blacklist'
                if is_blacklisted:
                    event_box.error(f"SECURITY ALERT: Blacklisted Vehicle!\nPlate: {data['text']} | Reason: {special_info[1]}")
                    # add to cache so it doesn't spam UI every frame
                    st.session_state['processed_tracks'].add(data['track_id'])
                    continue 
                img_filename=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_filename,processed_frame)
                status,msg,rec=db.handle_vehicle(data['text'],data['type'],img_filename,gate_mode)
                st.session_state['processed_tracks'].add(data['track_id'])
                refresh_metrics()
                fmt_time=time.strftime('%H:%M:%S',time.localtime())+f".{int((time.time()%1)*100):02d}"
                if status=="Entry":
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>🌟 VIP ENTRY: {data['text']}</b></div>",unsafe_allow_html=True)
                    else:event_box.success(f"ENTRY: {data['text']}\nTime: {fmt_time}")
                elif status=="Exit":
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>🌟 VIP EXIT: {data['text']} | Fee: $0.00</b></div>",unsafe_allow_html=True)
                    else:event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}\nTime: {rec['time']:.2f} min")
                else:event_box.error(msg)
        cap.release()
elif page=="Settings":cm.render_config_page()
elif page=="History":
    st.header("Financial & Parking Logs")
    conn=sqlite3.connect("parking.db")
    df_active=pd.read_sql_query("SELECT * FROM active_parking",conn)
    df_history=pd.read_sql_query("SELECT * FROM transaction_history ORDER BY id DESC",conn)
    sq=st.text_input("Search License Plate",placeholder="Type plate number...").strip().upper()
    if sq:
        df_active=df_active[df_active['plate_number'].str.contains(sq,case=False,na=False)]
        df_history=df_history[df_history['plate_number'].str.contains(sq,case=False,na=False)]
    if not df_active.empty:
        df_active['entry_time']=pd.to_datetime(df_active['entry_time']).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_active['evidence_img']=df_active['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    if not df_history.empty:
        for col in ['entry_time','exit_time']:df_history[col]=pd.to_datetime(df_history[col]).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_history['evidence_img']=df_history['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    cr,cd=st.columns([0.8,0.2])
    with cr:
        if st.button("Refresh History"):st.rerun()
    with cd:
        if not df_history.empty:
            st.download_button("Download CSV",df_history.to_csv(index=False).encode('utf-8'),f"parking_report_{time.strftime('%Y%m%d')}.csv","text/csv")
    st.subheader("Live Parking Status")
    if df_active.empty and sq:st.warning(f"No active vehicle found for '{sq}'")
    else:st.data_editor(df_active,column_config={"evidence_img":st.column_config.ImageColumn("Evidence"),"image_path":None,"plate_number":"License Plate","vehicle_type":"Type"},use_container_width=True,hide_index=True)
    st.markdown("---")
    st.subheader("Transaction History")
    if df_history.empty and sq:st.warning(f"No history found for '{sq}'")
    elif not df_history.empty:
        st.data_editor(df_history.style.format({"total_fee":"{:.2f}","duration_min":"{:.2f}"}),column_config={"evidence_img":st.column_config.ImageColumn("Entry Photo"),"image_path":None,"plate_number":"License Plate","total_fee":st.column_config.NumberColumn("Fee ($)",format="$%.2f")},use_container_width=True,hide_index=True)
        st.metric("Total Revenue (Filtered)",f"${df_history['total_fee'].sum():.2f}")
    conn.close()
elif page=="Security":
    st.header("Security & VIP Management")
    with st.form("add_special_plate"):
        c1,c2,c3=st.columns(3)
        new_plate=c1.text_input("License Plate").strip().upper()
        new_cat=c2.selectbox("Category",["VIP","Blacklist"])
        new_note=c3.text_input("Note/Reason")
        if st.form_submit_button("Add to System"):
            if new_plate:
                db.add_special_plate(new_plate,new_cat,new_note)
                st.success(f"Added {new_plate} as {new_cat}")
                time.sleep(1)
                st.rerun()
    st.markdown("---")
    st.subheader("Registered Plates")
    plates=db.get_all_special_plates()
    if plates:
        df_special=pd.DataFrame(plates,columns=["Plate","Category","Note"])
        st.dataframe(df_special,use_container_width=True,hide_index=True)
        del_plate=st.selectbox("Select plate to remove",df_special["Plate"])
        if st.button("Remove Plate"):
            db.remove_special_plate(del_plate)
            st.success("Plate removed")
            time.sleep(1)
            st.rerun()
    else:st.info("No special plates registered yet.")
elif page=="Analytics":
    st.header("Business Intelligence")
    conn=sqlite3.connect("parking.db")
    df_history=pd.read_sql_query("SELECT * FROM transaction_history",conn)
    df_active=pd.read_sql_query("SELECT * FROM active_parking",conn)
    conn.close()
    if not df_history.empty or not df_active.empty:
        c1,c2=st.columns(2)
        with c1:
            st.subheader("Traffic by Hour")
            e1=df_history[['entry_time']].copy() if not df_history.empty else pd.DataFrame(columns=['entry_time'])
            e2=df_active[['entry_time']].copy() if not df_active.empty else pd.DataFrame(columns=['entry_time'])
            all_e=pd.concat([e1,e2])
            all_e['entry_time']=pd.to_datetime(all_e['entry_time'])
            all_e['hour']=all_e['entry_time'].dt.hour
            st.bar_chart(all_e.groupby('hour').size(),color="#FF4B4B")
        with c2:
            st.subheader("Revenue by Day")
            if not df_history.empty:
                df_history['exit_time']=pd.to_datetime(df_history['exit_time'])
                df_history['day_of_week']=pd.Categorical(df_history['exit_time'].dt.day_name(),categories=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],ordered=True)
                st.bar_chart(df_history.groupby('day_of_week')['total_fee'].sum(),color="#00C246")
            else:st.info("No revenue data available yet.")
    else:st.warning("Not enough data to generate analytics. Process some vehicles first!")


# end
# python -m streamlit run main.py 
# (run in powershell)