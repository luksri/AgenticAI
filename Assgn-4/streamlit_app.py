import streamlit as st
import httpx
import json

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="Knowledge Collector", page_icon="🧠", layout="wide")

st.title("🧠 Knowledge Collector (Streamlit Mode)")

# Sidebar Stats
with st.sidebar:
    st.header("📊 Stats")
    try:
        stats = httpx.get(f"{BACKEND_URL}/stats").json()
        st.metric("Total Docs", stats["total_docs"])
        st.metric("Topics", stats["total_topics"])
        st.metric("Sources", stats["total_sources"])
        
        st.divider()
        st.header("🗂️ Topics")
        for t in stats["topics"]:
            st.text(f"📁 {t['name']} ({t['doc_count']} docs)")
    except:
        st.warning("Could not reach backend")

# Main Chat
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask your knowledge base..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = httpx.post(
                    f"{BACKEND_URL}/query",
                    json={
                        "query": prompt,
                        "messages": st.session_state.messages[:-1]
                    },
                    timeout=180
                ).json()
                
                # Show tools used
                if response.get("tools_used"):
                    with st.expander("🛠️ Tools used", expanded=False):
                        for tool in response["tools_used"]:
                            st.write(f"- `{tool}`")
                
                answer = response["answer"]
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
                # Check for dashboard
                if response.get("visuals"):
                    for vis in response["visuals"]:
                        if vis["type"] == "dashboard":
                            with st.expander(f"📊 Dashboard: {vis['title']}", expanded=True):
                                spec = vis["spec"]
                                params = spec.get("params", {})
                                st.subheader(params.get("title", "Untitled Dashboard"))
                                
                                # Render Tabs as separate sections in Streamlit
                                for tab in params.get("tabs", []):
                                    st.markdown(f"### 📑 {tab['name']}")
                                    cols = st.columns(min(len(tab.get("widgets", [])), 3) or 1)
                                    for i, w in enumerate(tab.get("widgets", [])):
                                        with cols[i % len(cols)]:
                                            kind = w.get("kind")
                                            if kind == "stat":
                                                st.metric(w.get("label"), w.get("value"), help=w.get("sub"))
                                            elif kind == "bar":
                                                st.bar_chart(w.get("data"), x=w.get("x_key"), y=w.get("y_keys")[0])
                                            elif kind == "line":
                                                st.line_chart(w.get("data"), x=w.get("x_key"), y=w.get("y_keys")[0])
                                            elif kind == "pie":
                                                st.write(f"Pie: {w.get('title')}")
                                                st.table(w.get("data"))
                                            elif kind == "checklist":
                                                st.write(f"**{w.get('title', 'Checklist')}**")
                                                for item in w.get("items", []):
                                                    st.checkbox(item["label"], value=item["checked"], key=f"{vis['title']}_{item['label']}")
                                            elif kind == "text":
                                                st.markdown(f"**{w.get('heading')}**")
                                                st.write(w.get("body"))
                                            else:
                                                st.info(f"Widget: {kind}")
            except Exception as e:
                st.error(f"Error: {e}")
                st.exception(e)
