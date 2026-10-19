function r = oe_solve(inputPath, commands, solveFrom, solveTo, opts)
%OE_SOLVE Solve one scenario against a release or forecast and wait for it.
%   R = OE_SOLVE(INPUTPATH, COMMANDS, SOLVEFROM, SOLVETO) submits a solve
%   of the input forecast INPUTPATH (a release path or the struct from
%   OE_RESOLVE_RELEASE) over SOLVEFROM:SOLVETO (e.g. '2026Q3', '2031Q4')
%   and waits until it finishes. COMMANDS is one of:
%       - a path to a .3fs command file
%       - command lines as a char (newline-separated), string array or
%         cell array, e.g. {'MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2'; ...}
%       - a command struct array from OE_READ_3FS
%   Comment lines (#), inline comments and blank lines are dropped and
%   n@v value runs are expanded before the commands are sent.
%
%   R = OE_SOLVE(..., OPTS) with OPTS fields:
%       outputPath      full output path; it must not exist yet
%       outputFolder    folder for an automatic output path (default '/me');
%                       the forecast is saved as
%                       '<outputFolder>/<name>-<yyyyMMdd-HHmmss>'
%       name            scenario name used in that path (default 'scenario')
%       wait            false returns right after submission (default true)
%       pollSeconds     pause between status checks when the long-poll
%                       endpoint is unavailable (default 10)
%       timeoutSeconds  give up waiting after this long (default 3600)
%
%   R is a struct with fields name, status ('Succeeded' or the final
%   status), operationId, outputPath, forecastId (id of the solved
%   forecast, '' unless it succeeded), seconds, failure (reason text),
%   submittedAt and commands (the text that was sent). A failed solve
%   gives a warning, not an error, so a batch of solves can carry on.
%
%   Example:
%       rel = oe_resolve_release('latest:5yr');
%       cmds = {'INCREASE RFED:US 2027Q1 1, 1, 1, 1'; 'FIX RFED:US 2027Q1:2027Q4'};
%       r = oe_solve(rel, cmds, '2026Q3', '2031Q4', struct('name', 'us_rate_up'));
%       T = oe_fetch(r.forecastId, {'GDP'}, {'US'}, struct('label', r.name));
%       % Mnemonics are examples: check them in your own catalogue.
%
%   See also OE_READ_3FS, OE_RUN_SCENARIOS, OE_FETCH.

if nargin < 5
    opts = struct();
end
o = merge_opts(opts, struct('outputPath', '', 'outputFolder', '/me', 'name', 'scenario', 'wait', true, ...
    'pollSeconds', 10, 'timeoutSeconds', 3600), 'oe_solve');
if isstruct(inputPath)
    if ~isfield(inputPath, 'Path') || isempty(inputPath.Path)
        error('oe:badInput', ['The input resource has no Path. Solves need a release or forecast ' ...
            'path, e.g. from oe_resolve_release(''latest:5yr'').']);
    end
    inputPath = inputPath.Path;
end
inputPath = char(inputPath);
solveFrom = check_period(solveFrom, 'solveFrom');
solveTo = check_period(solveTo, 'solveTo');
txt = commands_text(commands);
if isempty(txt)
    error('oe:badInput', 'No commands to solve: the command list is empty after removing comments.');
end

outPath = char(o.outputPath);
if isempty(outPath)
    folder = regexprep(char(o.outputFolder), '/+$', '');
    slug = regexprep(char(o.name), '[^A-Za-z0-9_.-]+', '_');
    outPath = sprintf('%s/%s-%s', folder, slug, char(datetime('now', 'Format', 'yyyyMMdd-HHmmss')));
end

body = struct('InputForecast', inputPath, ...
    'SolutionRange', struct('From', solveFrom, 'To', solveTo), ...
    'Commands', txt, ...
    'OutputForecast', outPath);
t0 = tic;
submitted = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
op = oe_api('POST', '/v1/operations/solve', body);
opId = field_text(op, 'Id');
status = field_text(op, 'Status');
r = struct('name', char(o.name), 'status', status, 'operationId', opId, 'outputPath', outPath, ...
    'forecastId', '', 'seconds', NaN, 'failure', '', 'submittedAt', submitted, 'commands', txt);
fprintf('Solve "%s" submitted (operation %s) -> %s\n', r.name, opId, outPath);
if ~o.wait
    return
end
if isempty(opId)
    error('oe:solve', 'The solve request returned no operation id; nothing to wait for.');
end

opPath = ['/v1/operations/' oe_quote_path(opId)];
useAwait = true;
while is_pending(status) && toc(t0) < o.timeoutSeconds
    tCall = tic;
    if useAwait
        try
            op = oe_api('GET', [opPath '/await']);
        catch
            useAwait = false;   % no long-poll endpoint: plain polling from now on
            op = oe_api('GET', opPath);
        end
    else
        pause(o.pollSeconds);
        op = oe_api('GET', opPath);
    end
    if isstruct(op) && isfield(op, 'Status')
        status = field_text(op, 'Status');
    end
    if is_pending(status) && toc(tCall) < 2
        pause(o.pollSeconds);   % the long poll returned at once; do not spin
    end
end

r.status = status;
r.seconds = toc(t0);
if strcmpi(status, 'Succeeded')
    res = oe_resource(outPath);
    r.forecastId = field_text(res, 'Id');
    fprintf('Solve "%s" succeeded in %.0f s\n', r.name, r.seconds);
else
    if is_pending(status)
        r.failure = sprintf('Still %s after %.0f s; check the operation later.', status, r.seconds);
    else
        r.failure = failure_text(op);
    end
    warning('oe:solveFailed', 'Solve "%s" ended with status %s: %s', r.name, status, r.failure);
end
end

function p = check_period(p, label)
[~, ~, P] = period_parts(p);
if numel(P) ~= 1 || isempty(P{1})
    error('oe:badPeriod', '%s must be a period such as ''2026Q3'' (or ''2026'').', label);
end
p = P{1};
end

function tf = is_pending(status)
tf = any(strcmpi(status, {'Queued', 'InProgress', 'Running', 'Pending', 'NotStarted'}));
end

function s = failure_text(op)
s = field_text(op, {'FailureReason', 'Error', 'Message'});
if isempty(s) && isstruct(op)
    for f = {'FailureReason', 'Error'}
        if isfield(op, f{1}) && ~isempty(op.(f{1}))
            s = jsonencode(op.(f{1}));
            return
        end
    end
end
if isempty(s)
    s = 'no reason given';
end
end

function txt = commands_text(c)
% Normalise every accepted command form to newline-joined lines.
if isstruct(c)
    txt = strtrim(oe_write_3fs(c, '', struct('decimals', 12)));
    lines = strsplit(txt, newline);
elseif (ischar(c) && size(c, 1) <= 1) || (isstring(c) && isscalar(c))
    c = char(c);
    if ~contains(c, newline) && ~isempty(regexpi(strtrim(c), '\.3fs$', 'once'))
        if ~isfile(strtrim(c))
            error('oe:badInput', 'Command file not found: %s', strtrim(c));
        end
        c = fileread(strtrim(c));
    end
    lines = strsplit(regexprep(c, '\r\n?', '\n'), newline);
elseif ischar(c)
    lines = cellstr(c);
elseif isstring(c) || iscellstr(c)
    lines = cellstr(c);
else
    error('oe:badInput', 'Commands must be a .3fs path, text lines or a struct array from oe_read_3fs.');
end
lines = regexprep(lines(:)', '#.*$', '');
lines = strtrim(lines);
lines = lines(~cellfun(@isempty, lines));
for i = 1:numel(lines)
    lines{i} = expand_repeats(lines{i});
end
txt = strjoin(lines, newline);
end

function s = expand_repeats(s)
% '4@1.2' -> '1.2, 1.2, 1.2, 1.2' (sent expanded so the server never sees n@v).
[tok, a, b] = regexp(s, '(?<![\w.])(\d+)@([^,\s]+)', 'tokens', 'start', 'end');
for k = numel(tok):-1:1
    n = str2double(tok{k}{1});
    rep = strjoin(repmat(tok{k}(2), 1, n), ', ');
    s = [s(1:a(k) - 1) rep s(b(k) + 1:end)];
end
end
