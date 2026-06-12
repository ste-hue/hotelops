"""Entry standalone dashboard F&B.

Run: streamlit run verticals/condges/app_fb.py
Il hub (verticals/hub/) NON usa questo file: importa fb_dashboard.render.
"""
import streamlit as st

from verticals.condges.fb_dashboard import render

st.set_page_config(page_title="F&B — Hotel Panorama", page_icon="🍽️",
                   layout="wide")
render()
