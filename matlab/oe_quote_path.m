function q = oe_quote_path(p)
%OE_QUOTE_PATH Percent-encode each segment of a resource path, keeping the slashes.
%   Q = OE_QUOTE_PATH(P) strips leading and trailing '/', drops empty
%   segments and encodes every character outside A-Z a-z 0-9 - . _ ~ as
%   %XX of its UTF-8 bytes. The result is ready to append to
%   '/v1/resources/'.
%
%   Example:
%       oe_quote_path('/me/my runs/test 1')
%       % -> 'me/my%20runs/test%201'
%
%   See also OE_RESOURCE, OE_API.

p = char(p);
segs = strsplit(p, '/');
segs = segs(~cellfun(@isempty, segs));
for i = 1:numel(segs)
    segs{i} = encode_segment(segs{i});
end
q = strjoin(segs, '/');
end

function out = encode_segment(s)
bytes = unicode2native(s, 'UTF-8');
keep = (bytes >= 48 & bytes <= 57) | (bytes >= 65 & bytes <= 90) | (bytes >= 97 & bytes <= 122) ...
    | bytes == 45 | bytes == 46 | bytes == 95 | bytes == 126;
parts = cell(1, numel(bytes));
for k = 1:numel(bytes)
    if keep(k)
        parts{k} = char(bytes(k));
    else
        parts{k} = sprintf('%%%02X', bytes(k));
    end
end
out = [parts{:}];
end
