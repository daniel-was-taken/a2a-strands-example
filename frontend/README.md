# Frontend (Reference Implementation)

This frontend was built for the orchestrator, which has been removed from the framework. The HTML/CSS/JS files are kept as a reference for building a custom UI on top of the A2A agent framework.

The `app.js` client expects a REST API with conversation endpoints (`/conversations`, `/conversations/{id}/messages`). To use this frontend, build a backend that exposes those endpoints and routes messages to agents via A2A.
