# Email and Calendar Security

Email search/read and calendar availability are L0. Drafting an email is a local L1 action. Sending email or creating a calendar event is L2 and requires an explicit task-scoped approval.

Approval records include action, impact, risk, requester, evidence, creation, and a 30-minute expiry. Rejection or expiry cancels the task. Direct email/calendar APIs also require an approved L2 task that references the concrete draft or meeting title.

Email completion requires provider message and thread identifiers. Calendar completion requires a provider event identifier. A click, request acceptance, empty response, or provider error cannot become verified success.

Contact resolution returns resolved, ambiguous, or not-found. Ambiguous matches are never selected automatically. Do-not-contact CRM records block outreach drafting and contacted/replied transitions.

Gmail and Google Calendar production providers are disconnected by default. Their interfaces and safe OAuth boundary are implemented; no live read or write is claimed until credentials and real transport are configured and verified.
