function s = field_text(rec, names)
%FIELD_TEXT First non-empty field among NAMES, as char (private helper).
%   S = FIELD_TEXT(REC, NAMES) returns '' when REC is not a struct or none
%   of the fields holds a scalar text, number or logical value.

s = '';
if ~isstruct(rec)
    return
end
if ischar(names)
    names = {names};
end
for i = 1:numel(names)
    if ~isfield(rec, names{i})
        continue
    end
    v = rec.(names{i});
    if ischar(v) && ~isempty(v)
        s = v;
    elseif isstring(v) && isscalar(v)
        s = char(v);
    elseif (isnumeric(v) || islogical(v)) && isscalar(v)
        s = char(string(v));
    end
    if ~isempty(s)
        return
    end
end
end
