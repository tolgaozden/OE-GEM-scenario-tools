function cmds = oe_read_3fs(source)
%OE_READ_3FS Parse a scenario command file (.3fs) into a struct array.
%   CMDS = OE_READ_3FS(FILE) reads one command per line. Blank lines and
%   comments (from # to the end of the line) are skipped. CMDS has one
%   element per command with fields
%       verb     'SET', 'FIX', 'UNFIX', 'MULTIPLY', 'INCREASE' (upper case)
%       target   'VAR:GROUP', or '&VAR:GROUP' for an equation residual
%       start    first period, e.g. '2027Q1'
%       stop     last period: the FIX/UNFIX window end, or for value
%                commands start + (number of values - 1) periods
%                (named stop because end is a MATLAB keyword)
%       values   row vector of values ([] for FIX/UNFIX); n@v is
%                expanded to n copies of v
%   CMDS = OE_READ_3FS(TEXT) parses command text instead of a file when
%   TEXT is a cell/string array of lines, contains a newline, or starts
%   with a command verb.
%
%   Accepted line forms:
%       SET VAR:GRP 2027Q1 v1, v2, v3       value commands (SET, MULTIPLY,
%       MULTIPLY VAR:GRP 2027Q1 4@1.2        INCREASE); commas and/or
%       INCREASE &VAR:GRP 2027Q1 -0.5, -0.5  spaces separate values
%       FIX VAR:GRP 2027Q1:2027Q4            window commands (FIX, UNFIX)
%   Other verbs are kept with a warning.
%
%   Example:
%       cmds = oe_read_3fs({'MULTIPLY WPO_EQN:WORLD 2027Q1 4@1.2', ...
%                           'FIX WPO_EQN:WORLD 2027Q1:2027Q4'});
%       cmds(1).values      % [1.2 1.2 1.2 1.2]
%
%   See also OE_WRITE_3FS, OE_SOLVE.

[lines, label] = source_lines(source);
known = {'SET', 'FIX', 'UNFIX', 'MULTIPLY', 'INCREASE'};
cmds = struct('verb', {}, 'target', {}, 'start', {}, 'stop', {}, 'values', {});
for ln = 1:numel(lines)
    line = strtrim(regexprep(lines{ln}, '#.*$', ''));
    if isempty(line)
        continue
    end
    where = sprintf('%s line %d', label, ln);
    tok = regexp(line, '^(\S+)\s+(\S+)\s+(\S+)\s*(.*)$', 'tokens', 'once');
    if isempty(tok)
        error('oe:badCommand', '%s: expected "VERB TARGET PERIOD [VALUES]", got "%s".', where, line);
    end
    tok(end + 1:4) = {''};
    verb = upper(tok{1});
    target = tok{2};
    pspec = tok{3};
    rest = strtrim(tok{4});
    if ~ismember(verb, known)
        warning('oe:unknownVerb', '%s: unknown verb "%s" (known: %s); kept as written.', ...
            where, verb, strjoin(known, ', '));
    end
    parts = strsplit(pspec, ':');
    if numel(parts) > 2
        error('oe:badCommand', '%s: bad period "%s".', where, pspec);
    end
    start = norm_one(parts{1}, where);
    stop = '';
    if numel(parts) == 2
        stop = norm_one(parts{2}, where);
    end
    isWindow = ismember(verb, {'FIX', 'UNFIX'});
    if isWindow && isempty(stop) && ~isempty(regexp(rest, '^\d{4}(Q[1-4])?$', 'once', 'ignorecase'))
        stop = norm_one(rest, where);   % 'FIX X:Y 2027Q1 2027Q4' form
        rest = '';
    end
    values = parse_values(rest, where);
    if isWindow
        if ~isempty(values)
            error('oe:badCommand', '%s: %s takes a window (e.g. 2027Q1:2027Q4), not values.', where, verb);
        end
        if isempty(stop)
            stop = start;
        end
    elseif ismember(verb, known)
        if isempty(values)
            error('oe:badCommand', '%s: %s needs at least one value after the start period.', where, verb);
        end
        if isempty(stop)
            last = period_shift(start, numel(values) - 1);
            stop = last{1};
        end
    end
    cmds(end + 1) = struct('verb', verb, 'target', target, 'start', start, 'stop', stop, ...
        'values', values); %#ok<AGROW>
end
end

function [lines, label] = source_lines(source)
label = 'commands';
if isstring(source) && ~isscalar(source)
    source = cellstr(source);
end
if iscell(source)
    lines = cellstr(source);
    lines = lines(:)';
    return
end
source = char(source);
verbs = '^\s*(SET|FIX|UNFIX|MULTIPLY|INCREASE)\s';
if contains(source, newline) || (~isfile(source) && ~isempty(regexpi(source, verbs, 'once')))
    text = source;
elseif isfile(source)
    text = fileread(source);
    label = source;
else
    error('oe:badInput', 'Command file not found: %s', source);
end
lines = strsplit(regexprep(text, '\r\n?', '\n'), newline);
end

function p = norm_one(s, where)
[~, ~, P] = period_parts(s);
if isempty(P{1}) || isempty(regexp(upper(s), '^\d{4}(Q[1-4])?$', 'once'))
    error('oe:badCommand', '%s: bad period "%s"; use e.g. 2027Q1 or 2027.', where, s);
end
p = P{1};
end

function v = parse_values(s, where)
v = [];
if isempty(s)
    return
end
items = regexp(s, '[,\s]+', 'split');
items = items(~cellfun(@isempty, items));
parts = cell(1, numel(items));
for i = 1:numel(items)
    it = items{i};
    if contains(it, '@')
        nv = strsplit(it, '@');
        n = str2double(nv{1});
        x = str2double(nv{end});
        if numel(nv) ~= 2 || isnan(n) || n < 1 || n ~= round(n) || isnan(x)
            error('oe:badCommand', '%s: bad repeat "%s"; use n@value, e.g. 4@1.2.', where, it);
        end
        parts{i} = repmat(x, 1, n);
    else
        x = str2double(it);
        if isnan(x)
            error('oe:badCommand', '%s: "%s" is not a number.', where, it);
        end
        parts{i} = x;
    end
end
v = [parts{:}];
end
