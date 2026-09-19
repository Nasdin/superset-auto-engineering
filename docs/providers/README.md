# Provider contract references

The implementation uses the Devin organization API v3. Checked against official documentation during implementation:

- [Create organization session](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions.md)
- [Get organization session](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session.md)
- [Get session attachments](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session-attachments.md)

Create includes `prompt`, `title`, `tags`, `repos`, `max_acu_limit`, `structured_output_schema`, and `structured_output_required`. Readback uses `session_id`, `url`, `status`, `status_detail`, `structured_output`, and `acus_consumed`. Completion is `status_detail=finished`; an exited/suspended session alone is not proof of success. Attachments must be identified by the provider and have `source=devin`.

These source contracts are not a substitute for a successful request using the intended organization's credentials. The paid create/poll/artifact path still needs live qualification.
