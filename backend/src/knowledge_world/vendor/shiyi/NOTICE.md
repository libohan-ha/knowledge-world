Copied from the user-provided `shiyi-api-v2/scripts` package on 2026-10-10.
The original MIT license is retained in LICENSE.

Local change: `shiyi_tools.py` uses a relative package import.
The application uses the tool schemas, validation and GET-only dispatcher with
`knowledge_world.shiyi.ReadOnlyClient`, which bounds responses and rejects every
write method. The original CLI is not registered as an Agent tool or application
command. Credentials are supplied explicitly by Knowledge World's server settings.
