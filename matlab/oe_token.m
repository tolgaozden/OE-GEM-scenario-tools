function token = oe_token()
%OE_TOKEN Read the Oxford Economics API token from the OE_TOKEN environment variable.
%   TOKEN = OE_TOKEN() returns the bearer token, trimmed. A leading
%   "Bearer " is removed if it was pasted along with the token. The token
%   is never printed. If OE_TOKEN is not set, the error explains how to set
%   it. Tokens expire after about 24 hours.
%
%   Set the token once per session, in one of these ways:
%       MATLAB:      setenv('OE_TOKEN', '<your token>')
%       MATLAB:      oe_login(username, password)   % see oe_login
%       PowerShell:  $env:OE_TOKEN = "<your token>"   (before starting MATLAB)
%       bash:        export OE_TOKEN="<your token>"   (before starting MATLAB)
%
%   Example:
%       setenv('OE_TOKEN', '<your token>');
%       t = oe_token();        % used internally by oe_api
%
%   See also OE_LOGIN, OE_API.

token = strtrim(getenv('OE_TOKEN'));
if strncmpi(token, 'Bearer ', 7)
    token = strtrim(token(8:end));
end
if isempty(token)
    error('oe:noToken', ['OE_TOKEN is not set. Set it once per session:\n' ...
        '  MATLAB:      setenv(''OE_TOKEN'', ''<your token>'')\n' ...
        '  MATLAB:      oe_login(username, password)\n' ...
        '  PowerShell:  $env:OE_TOKEN = "<your token>"   (then start MATLAB from that shell)\n' ...
        '  bash:        export OE_TOKEN="<your token>"   (then start MATLAB from that shell)\n' ...
        'Tokens expire after about 24 hours.']);
end
end
