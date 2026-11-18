"use strict";
// Each panel selects only its existing owner bridge. Hosts validate operations.
window.TLPanel.connect = (name, { asynchronous = false } = {}) =>
  new Promise((resolve) => {
    const pending = new Map();
    let sequence = 0;
    const settle = (id, value, error) => {
      if (!pending.has(id)) return;
      const [accept, reject] = pending.get(id);
      pending.delete(id);
      error ? reject(new Error(error)) : accept(value);
    };
    const environment = (value) =>
      window.dispatchEvent(
        new CustomEvent(`${name}-environment`, { detail: value }),
      );
    if (location.protocol === "file:") {
      const script = document.createElement("script");
      script.src = "qrc:///qtwebchannel/qwebchannel.js";
      script.onload = () =>
        new QWebChannel(qt.webChannelTransport, (channel) => {
          const bridge = channel.objects[name];
          bridge.environment.connect((value) => environment(JSON.parse(value)));
          window[`${name}Ready`] = () => bridge.ready();
          if (asynchronous) {
            bridge.response.connect((id, value) => {
              const result = JSON.parse(value);
              settle(id, result.data, result.error);
            });
          }
          resolve(
            (path, body) =>
              new Promise((accept, reject) => {
                if (asynchronous) {
                  const id = ++sequence;
                  pending.set(id, [accept, reject]);
                  bridge.requestAsync(id, path, JSON.stringify(body ?? {}));
                } else {
                  bridge.request(
                    path,
                    JSON.stringify(body ?? null),
                    (value) => {
                      const result = JSON.parse(value);
                      result.error
                        ? reject(new Error(result.error))
                        : accept(result.data);
                    },
                  );
                }
              }),
          );
        });
      document.head.append(script);
    } else {
      window.addEventListener("message", (event) => {
        if (event.source !== parent || event.origin !== location.origin) return;
        const message = event.data;
        if (message?.type === `${name}-environment`) environment(message.value);
        if (message?.type === `${name}-response`)
          settle(message.id, message.value, message.error);
      });
      window[`${name}Ready`] = () =>
        parent.postMessage({ type: `${name}-ready` }, location.origin);
      resolve(
        (path, body) =>
          new Promise((accept, reject) => {
            const id = ++sequence;
            pending.set(id, [accept, reject]);
            parent.postMessage(
              { type: `${name}-request`, id, path, body },
              location.origin,
            );
          }),
      );
    }
  });
