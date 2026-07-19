import "./state.js";
import "./api.js";
import "./sse.js";
import { boot } from "./render/chat.js";
import { renderResultNotice } from "./render/ui.js";

boot().catch((error) => {
  renderResultNotice(error instanceof Error ? error.message : String(error), "error");
});
