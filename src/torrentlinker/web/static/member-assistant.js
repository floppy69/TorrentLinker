"use strict";
const memberChat = {id: "", messages: []};
async function loadMemberAssistant() {
  const data = await api("member-assistant"), root = $("view-member-assistant");
  root.replaceChildren(requestNode("h2", "Assistant"), requestNode("p", say(`${data.usage.remaining} of ${data.usage.limit} messages left today. Resets at server midnight.`, `${data.usage.remaining} messages sur ${data.usage.limit} restants aujourd’hui. Remise à zéro à minuit sur le serveur.`)));
  const controls = requestNode("div", undefined, "toolbar"), discussions = requestNode("select");
  discussions.setAttribute("aria-label", say("Discussion", "Discussion"));
  discussions.append(new Option(say("New discussion", "Nouvelle discussion"), ""));
  for (const row of data.conversations) discussions.append(new Option(row.title, row.id));
  discussions.value = memberChat.id;
  discussions.onchange = () => guard(async () => {memberChat.id = discussions.value; memberChat.messages = memberChat.id ? (await api(`member-assistant/${memberChat.id}`)).messages : []; await loadMemberAssistant();});
  const remove = requestNode("button", say("Delete discussion", "Supprimer la discussion")); remove.disabled = !memberChat.id;
  remove.onclick = (event) => guard(async () => {await api(`member-assistant/${memberChat.id}`, undefined, "DELETE"); memberChat.id = ""; memberChat.messages = []; await loadMemberAssistant();}, event.currentTarget);
  controls.append(discussions, remove); root.append(controls);
  const transcript = requestNode("div", undefined, "request-list"); transcript.setAttribute("role", "log");
  for (const row of memberChat.messages) {
    const block = requestNode("section", undefined, "card");
    block.append(requestNode("strong", row.role === "user" ? say("You", "Vous") : "Assistant"));
    const content = requestNode("p", row.content); content.style.whiteSpace = "pre-wrap"; block.append(content); transcript.append(block);
  }
  root.append(transcript);
  const form = requestNode("form", undefined, "card"), message = requestNode("textarea"); message.required = true; message.maxLength = 16000;
  message.setAttribute("aria-label", say("Message", "Message"));
  const send = requestNode("button", say("Send", "Envoyer")); send.type = "submit"; send.disabled = data.usage.remaining === 0;
  const error = requestNode("p", "", "field-error"); error.setAttribute("role", "alert");
  form.onsubmit = async event => {
    event.preventDefault(); send.disabled = true; discussions.disabled = true; remove.disabled = true; error.textContent = "";
    try {const result = await api("member-assistant", {conversation_id: memberChat.id, message: message.value}); memberChat.id = result.conversation.id; memberChat.messages = result.conversation.messages; await loadMemberAssistant();}
    catch (failure) {error.textContent = failure.message; send.disabled = false; discussions.disabled = false; remove.disabled = !memberChat.id;}
  };
  form.append(message, send, error); root.append(form);
}
document.addEventListener("tl-logout", () => {memberChat.id = ""; memberChat.messages = [];});
