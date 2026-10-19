function res = oe_resource(path)
%OE_RESOURCE Get a release, forecast or workspace folder by its path.
%   RES = OE_RESOURCE(PATH) returns the decoded resource: a struct with
%   fields such as Id, Name, Path, Type and, for folders, Children. PATH
%   may be '/me' (your own workspace root), a workspace path such as
%   '/me/runs/oil_up-20270101-120000', or a release path such as
%   'oxford-economics/releases/Global Economic Model/Extension/<release>'.
%   Each path segment is percent-encoded for you.
%
%   Example:
%       me = oe_resource('/me');
%       {me.Children.Name}        % what is in your workspace (if any)
%
%   See also OE_RELEASES, OE_RESOLVE_RELEASE, OE_API.

p = strtrim(char(path));
if isempty(oe_quote_path(p))
    error('oe:badInput', 'Resource path is empty. Use ''/me'' for your own workspace root.');
end
res = oe_api('GET', ['/v1/resources/' oe_quote_path(p)]);
end
