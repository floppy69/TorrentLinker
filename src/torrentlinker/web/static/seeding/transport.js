"use strict";
let seedingRequest,
  environment = {},
  ready = false;
window.addEventListener("seeding-environment", (event) => {
  environment = event.detail;
  if (ready) applyEnvironment(environment);
});
window.addEventListener("DOMContentLoaded", async () => {
  init();
  const request = await TLPanel.connect("seeding", { asynchronous: true });
  seedingRequest = (action, body = {}) =>
    request(action, { ...body, _client: environment.state?.client_id });
  ready = true;
  window.seedingReady();
});
