function out = oe_api(method, path, body, opts)
%OE_API Send one request to the Oxford Economics model API and decode the reply.
%   OUT = OE_API(METHOD, PATH) sends a GET, POST, PUT, PATCH or DELETE
%   request with the bearer token from OE_TOKEN (see OE_TOKEN).
%   OUT = OE_API(METHOD, PATH, BODY) also sends BODY as JSON. BODY = []
%   sends no body. A char or string BODY is sent unchanged (already JSON);
%   anything else goes through jsonencode. Put a list of structs in a cell
%   array ({s1, s2}) so that even one element is sent as a JSON array.
%   OUT = OE_API(METHOD, PATH, BODY, OPTS) with OPTS fields:
%       timeout    seconds to wait for a response (default 180)
%       retries    extra attempts after network errors and HTTP
%                  429/502/503/504 (default 5)
%       backoff    first wait in seconds, doubled per attempt, capped at
%                  60 (default 2)
%       baseUrl    API root (default: env OE_BASE_URL, else
%                  https://model.oxfordeconomics.com/api)
%       raw        true returns the reply text without JSON decoding
%       quiet      true hides the retry messages
%       transport  function handle @(request, uri, httpOptions) returning
%                  a response; tests use it to replace the network
%                  (default: matlab.net.http send)
%
%   PATH is relative to the API root ('/v1/...') or a full https:// URL.
%   Encode resource path segments with OE_QUOTE_PATH. The reply loses any
%   UTF-8 byte-order mark; JSON is decoded with jsondecode, other text is
%   returned as char, and an empty reply gives [].
%
%   Error identifiers: 'oe:noToken' (OE_TOKEN not set), 'oe:httpNNN' for a
%   non-2xx status (e.g. 'oe:http404'), 'oe:network' when no response
%   arrived after all retries. Error messages never contain the token.
%
%   Example:
%       me = oe_api('GET', '/v1/resources/me');
%       ind = oe_api('GET', ['/v1/forecast-contents/' id '/indicators']);
%
%   See also OE_TOKEN, OE_QUOTE_PATH, OE_RESOURCE.

if nargin < 3
    body = [];
end
if nargin < 4
    opts = struct();
end
o = merge_opts(opts, struct('timeout', 180, 'retries', 5, 'backoff', 2, 'baseUrl', '', ...
    'raw', false, 'quiet', false, 'transport', []), 'oe_api');
method = upper(char(method));
if ~any(strcmp(method, {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}))
    error('oe:badInput', 'Unsupported method "%s": use GET, POST, PUT, PATCH or DELETE.', method);
end
token = oe_token();
url = full_url(char(path), o.baseUrl);

import matlab.net.http.*
hdrs = [HeaderField('Authorization', ['Bearer ' token]), HeaderField('Accept', 'application/json')];
if isnumeric(body) && isempty(body)
    req = RequestMessage(method, hdrs);
else
    if ischar(body) || isstring(body)
        json = char(body);
    else
        json = jsonencode(body);
    end
    mb = MessageBody();
    mb.Payload = unicode2native(json, 'UTF-8');
    req = RequestMessage(method, [hdrs, HeaderField('Content-Type', 'application/json')], mb);
end
httpOpts = HTTPOptions('ConnectTimeout', min(o.timeout, 30), 'ConvertResponse', false, 'SavePayload', true);
try
    httpOpts.ResponseTimeout = o.timeout;   % not available in every release
catch
end
% 'literal' keeps the percent-encoding made by oe_quote_path; without it
% the URI class would encode the % signs a second time.
uri = matlab.net.URI(url, 'literal');
sendFcn = o.transport;
if isempty(sendFcn)
    sendFcn = @send;
end

attempt = 0;
while true
    attempt = attempt + 1;
    try
        resp = sendFcn(req, uri, httpOpts);
    catch err
        if attempt <= o.retries
            wait_before_retry(o, attempt, method, url, 'network error');
            continue
        end
        msg = sprintf('%s %s: no response after %d attempt(s): %s', method, url, attempt, err.message);
        error('oe:network', '%s', redact(msg, token));
    end
    status = double(resp.StatusCode);
    if any(status == [429 502 503 504]) && attempt <= o.retries
        wait_before_retry(o, attempt, method, url, sprintf('HTTP %d', status));
        continue
    end
    break
end

txt = response_text(resp);
if status < 200 || status >= 300
    if numel(txt) > 800
        txt = [txt(1:800) ' ...'];
    end
    msg = sprintf('%s %s -> HTTP %d\n%s', method, url, status, txt);
    if status == 401
        msg = sprintf('%s\n(HTTP 401 usually means the token has expired: set a fresh OE_TOKEN.)', msg);
    end
    error(sprintf('oe:http%d', status), '%s', redact(msg, token));
end
if o.raw
    out = txt;
elseif isempty(strtrim(txt))
    out = [];
else
    try
        out = jsondecode(txt);
    catch
        out = txt;
    end
end
end

function url = full_url(path, baseUrl)
if startsWith(path, 'https://') || startsWith(path, 'http://')
    url = path;
    return
end
base = char(baseUrl);
if isempty(base)
    base = strtrim(getenv('OE_BASE_URL'));
end
if isempty(base)
    base = 'https://model.oxfordeconomics.com/api';
end
base = regexprep(base, '/+$', '');
if ~startsWith(path, '/')
    path = ['/' path];
end
url = [base path];
end

function wait_before_retry(o, attempt, method, url, why)
delay = min(60, o.backoff * 2 ^ (attempt - 1));
if ~o.quiet
    fprintf('oe_api: %s %s: %s; retry %d of %d in %.0f s\n', method, url, why, attempt, o.retries, delay);
end
pause(delay);
end

function txt = response_text(resp)
% Raw bytes are decoded as UTF-8 here (not by MATLAB) so that a leading
% byte-order mark can be removed before jsondecode sees the text.
txt = '';
b = resp.Body;
if isempty(b)
    return
end
try
    p = b.Payload;
catch
    p = [];
end
if ~isempty(p)
    bytes = reshape(uint8(p), 1, []);
    if numel(bytes) >= 3 && isequal(bytes(1:3), uint8([239 187 191]))
        bytes = bytes(4:end);
    end
    txt = native2unicode(bytes, 'UTF-8');
else
    try
        d = b.Data;
    catch
        d = [];
    end
    if ischar(d) || isstring(d)
        txt = char(d);
    elseif isa(d, 'uint8')
        txt = native2unicode(reshape(d, 1, []), 'UTF-8');
    elseif ~isempty(d)
        txt = jsonencode(d);
    end
end
txt = regexprep(txt, '^\x{FEFF}', '');
end

function msg = redact(msg, token)
if ~isempty(token)
    msg = strrep(msg, token, '<redacted>');
end
msg = regexprep(msg, '(?i)bearer\s+\S+', 'Bearer <redacted>');
end
