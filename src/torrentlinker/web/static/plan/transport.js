"use strict";
let planRequest;
let planEnvironment = {
  mode: "desktop",
  language: "en",
  theme: "dark",
  active: false,
  state: {},
};
window.addEventListener("plan-environment", (event) => {
  planEnvironment = event.detail;
  if (planRequest) planApplyEnvironment(event.detail);
});
window.addEventListener("DOMContentLoaded", async () => {
  planInit();
  const request = await TLPanel.connect("plan");
  planRequest = async (action, body = {}) => {
    const result = await request(action, {
      ...body,
      _client: planEnvironment.state?.client_id,
    });
    if (result?.action)
      throw Object.assign(Error(result.message), { action: result.action });
    return result;
  };
  window.planReady();
});
