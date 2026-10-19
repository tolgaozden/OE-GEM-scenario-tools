function id = forecast_id(x)
%FORECAST_ID Forecast id from a char/string id or a resource struct with an Id field (private helper).

if isstruct(x)
    if isfield(x, 'Id') && ~isempty(x.Id)
        x = x.Id;
    elseif isfield(x, 'forecastId') && ~isempty(x.forecastId)
        x = x.forecastId;   % result struct of oe_solve
    else
        error('oe:badInput', ['The struct has no Id. Pass a forecast id, the struct returned by ' ...
            'oe_resolve_release or oe_resource, or a succeeded oe_solve result.']);
    end
end
if isstring(x) && isscalar(x)
    x = char(x);
end
if ~ischar(x) || isempty(strtrim(x))
    error('oe:badInput', 'Forecast id must be non-empty text, e.g. res.Id from oe_resolve_release.');
end
id = strtrim(x);
end
