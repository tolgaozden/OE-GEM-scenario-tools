function recs = as_records(x)
%AS_RECORDS Turn decoded JSON (struct array or cell array) into a cell row of structs (private helper).
%   jsondecode returns a struct array when all objects share the same keys
%   and a cell array otherwise; callers loop over the result of this helper
%   so they need not care which one came back.

if isempty(x)
    recs = {};
elseif iscell(x)
    recs = reshape(x, 1, []);
elseif isstruct(x)
    recs = num2cell(reshape(x, 1, []));
else
    recs = {x};
end
end
