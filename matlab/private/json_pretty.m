function s = json_pretty(x)
%JSON_PRETTY jsonencode with indentation where the MATLAB release supports it (private helper).
%   PrettyPrint arrived in R2021a; older releases get compact JSON.

try
    s = jsonencode(x, 'PrettyPrint', true);
catch
    s = jsonencode(x);
end
end
