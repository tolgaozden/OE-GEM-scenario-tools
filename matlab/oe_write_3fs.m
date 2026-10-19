function txt = oe_write_3fs(cmds, file, opts)
%OE_WRITE_3FS Write scenario commands as .3fs text (and optionally a file).
%   TXT = OE_WRITE_3FS(CMDS) returns the command text, one command per
%   line. CMDS is a struct array as returned by OE_READ_3FS (fields verb,
%   target, start, stop, values) or a cell/string array of ready lines.
%   TXT = OE_WRITE_3FS(CMDS, FILE) also writes the text to FILE (UTF-8).
%   TXT = OE_WRITE_3FS(CMDS, FILE, OPTS) with OPTS fields:
%       header    comment text written first, one '# ' line per line
%       compact   true writes runs of equal values as n@v (default false)
%       decimals  decimals kept for values (default 6)
%
%   Lines look like
%       MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2
%       FIX WPO_EQN:WORLD 2027Q1:2027Q4
%
%   Example:
%       cmds = oe_read_3fs('my_scenario.3fs');
%       oe_write_3fs(cmds, 'copy.3fs', struct('header', 'Copy of my_scenario'));
%
%   See also OE_READ_3FS, OE_SOLVE.

if nargin < 2
    file = '';
end
if nargin < 3
    opts = struct();
end
o = merge_opts(opts, struct('header', '', 'compact', false, 'decimals', 6), 'oe_write_3fs');

lines = {};
if ~isempty(o.header)
    h = o.header;
    if ischar(h) || (isstring(h) && isscalar(h))
        h = strsplit(regexprep(char(h), '\r\n?', '\n'), newline);
    end
    h = cellstr(h);
    lines = strcat({'# '}, h(:)');
end

if isstruct(cmds)
    for i = 1:numel(cmds)
        lines{end + 1} = command_line(cmds(i), o); %#ok<AGROW>
    end
elseif ischar(cmds) || isstring(cmds) || iscellstr(cmds)
    c = cellstr(cmds);
    lines = [lines, strtrim(c(:)')];
else
    error('oe:badInput', 'Commands must be a struct array from oe_read_3fs or a list of lines.');
end
txt = [strjoin(lines, newline) newline];

if ~isempty(file)
    write_text(char(file), txt);
end
end

function s = command_line(c, o)
verb = upper(char(c.verb));
target = char(c.target);
stop = '';
if isfield(c, 'stop')
    stop = char(c.stop);
end
if any(strcmp(verb, {'FIX', 'UNFIX'})) || isempty(c.values)
    if isempty(stop)
        s = sprintf('%s %s %s', verb, target, char(c.start));
    else
        s = sprintf('%s %s %s:%s', verb, target, char(c.start), stop);
    end
    return
end
v = c.values(:)';
items = {};
i = 1;
while i <= numel(v)
    j = i;
    if o.compact
        while j < numel(v) && v(j + 1) == v(i)
            j = j + 1;
        end
    end
    if j > i
        items{end + 1} = sprintf('%d@%s', j - i + 1, fmt(v(i), o.decimals)); %#ok<AGROW>
    else
        items{end + 1} = fmt(v(i), o.decimals); %#ok<AGROW>
    end
    i = j + 1;
end
s = sprintf('%s %s %s %s', verb, target, char(c.start), strjoin(items, ', '));
end

function s = fmt(x, decimals)
s = sprintf('%.*f', decimals, x);
if contains(s, '.')
    s = regexprep(s, '0+$', '');
    s = regexprep(s, '\.$', '');
end
if strcmp(s, '-0')
    s = '0';
end
end
