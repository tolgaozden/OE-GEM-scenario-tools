function varargout = oe_login(username, password)
%OE_LOGIN Get an API token with an Oxford Economics username and password.
%   TOKEN = OE_LOGIN(USERNAME, PASSWORD) requests a token with the OAuth
%   password grant and returns it.
%   OE_LOGIN(USERNAME, PASSWORD) with no output argument stores the token
%   in the OE_TOKEN environment variable of this MATLAB session instead, so
%   it is never shown in the Command Window.
%
%   The identity-provider settings are not part of this toolkit. They come
%   from your own Oxford Economics account setup and must be supplied in
%   these environment variables:
%       OE_AUTH_DOMAIN       host name of the token service
%       OE_AUTH_CLIENT_ID    client id issued for API access
%       OE_AUTH_AUDIENCE     API audience identifier
%
%   Example:
%       setenv('OE_AUTH_DOMAIN', '<from your account setup>');
%       setenv('OE_AUTH_CLIENT_ID', '<from your account setup>');
%       setenv('OE_AUTH_AUDIENCE', '<from your account setup>');
%       oe_login(username, password)          % sets OE_TOKEN for this session
%
%   Do not save passwords or tokens in scripts.
%
%   See also OE_TOKEN.

names = {'OE_AUTH_DOMAIN', 'OE_AUTH_CLIENT_ID', 'OE_AUTH_AUDIENCE'};
vals = cellfun(@(n) strtrim(getenv(n)), names, 'UniformOutput', false);
missing = names(cellfun(@isempty, vals));
if ~isempty(missing)
    error('oe:authConfig', ['oe_login needs the environment variable(s) %s. These values come from ' ...
        'your own Oxford Economics account setup (ask your Oxford Economics contact) and are not ' ...
        'shipped with this toolkit. Set them first, for example:\n' ...
        '  setenv(''OE_AUTH_DOMAIN'', ''<domain>'')\n' ...
        '  setenv(''OE_AUTH_CLIENT_ID'', ''<client id>'')\n' ...
        '  setenv(''OE_AUTH_AUDIENCE'', ''<audience>'')\n' ...
        'or paste an existing token with setenv(''OE_TOKEN'', ''<your token>'').'], strjoin(missing, ', '));
end
if nargin < 2 || isempty(username) || isempty(password)
    error('oe:badInput', 'oe_login needs a username and a password: oe_login(username, password).');
end

domain = regexprep(vals{1}, '^https?://', '');
domain = regexprep(domain, '/+$', '');
url = ['https://' domain '/oauth/token'];
body = struct('grant_type', 'password', 'username', char(username), 'password', char(password), ...
    'audience', vals{3}, 'client_id', vals{2}, 'scope', 'openid profile');

import matlab.net.http.*
mb = MessageBody();
mb.Payload = unicode2native(jsonencode(body), 'UTF-8');
hdrs = [HeaderField('Content-Type', 'application/json'), HeaderField('Accept', 'application/json')];
req = RequestMessage('POST', hdrs, mb);
try
    resp = send(req, matlab.net.URI(url), HTTPOptions('ConnectTimeout', 30));
catch err
    % The message of a transport error never contains the request body.
    error('oe:network', 'Could not reach the token service at %s: %s', domain, err.message);
end

data = resp.Body.Data;
if ischar(data) || isstring(data)
    try
        data = jsondecode(char(data));
    catch
        data = struct();
    end
end
status = double(resp.StatusCode);
if status < 200 || status >= 300 || ~isstruct(data) || ~isfield(data, 'access_token')
    detail = '';
    if isstruct(data)
        if isfield(data, 'error'), detail = char(string(data.error)); end
        if isfield(data, 'error_description'), detail = [detail ': ' char(string(data.error_description))]; end
    end
    error('oe:auth', 'Login failed (HTTP %d) %s. Check the username, password and OE_AUTH_* settings.', ...
        status, detail);
end

token = char(data.access_token);
if nargout > 0
    varargout{1} = token;
else
    setenv('OE_TOKEN', token);
    hours = NaN;
    if isfield(data, 'expires_in'), hours = double(data.expires_in) / 3600; end
    fprintf('OE_TOKEN set for this MATLAB session (valid for about %.0f hours).\n', hours);
end
end
