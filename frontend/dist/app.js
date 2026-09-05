const form = document.querySelector("#chatForm");
const input = document.querySelector("#patientText");
const messages = document.querySelector("#messages");
const button = document.querySelector("#sendButton");
const statusBadge = document.querySelector("#statusBadge");
const noteEmpty = document.querySelector("#noteEmpty");
const noteContent = document.querySelector("#noteContent");

let sessionId = null;

function addMessage(role, content) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = content;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function setStatus(text) {
  statusBadge.textContent = text;
}

function renderNote(note) {
  noteEmpty.classList.add("hidden");
  noteContent.classList.remove("hidden");
  noteContent.innerHTML = `
    <span class="urgency ${note.urgency_level}">${note.urgency_level}</span>
    <div class="note-section">
      <h3>Urgency and Department</h3>
      <p>${note.department || "Human triage review required"}</p>
    </div>
    <div class="note-section">
      <h3>Rule and Rationale</h3>
      <p>${note.matched_rule_id || "No deterministic rule matched"}: ${note.rationale}</p>
    </div>
    <div class="note-section">
      <h3>Reported vs Established</h3>
      <p>${note.reported_vs_established}</p>
    </div>
    <div class="note-section">
      <h3>Remaining Unknowns</h3>
      <p>${note.remaining_unknowns.length ? note.remaining_unknowns.join(", ") : "None recorded"}</p>
    </div>
  `;
}

async function sendTurn(text) {
  const url = sessionId ? `/api/sessions/${sessionId}/reply` : "/api/sessions";
  const body = sessionId ? { answer: text } : { description: text };
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error("Request failed");
  }
  return response.json();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  addMessage("patient", text);
  input.value = "";
  button.disabled = true;
  setStatus("Thinking");

  try {
    const result = await sendTurn(text);
    sessionId = result.session_id;
    if (result.next_question) {
      addMessage("assistant", result.next_question);
      button.textContent = "Reply";
      setStatus("Awaiting answer");
    }
    if (result.triage_note) {
      renderNote(result.triage_note);
      setStatus(result.status);
      button.textContent = "Reply";
    }
  } catch (error) {
    addMessage("assistant", "Something went wrong. Please try again or ask a human triage reviewer to continue.");
    setStatus("Error");
  } finally {
    button.disabled = false;
    input.focus();
  }
});
