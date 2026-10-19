function L = oe_eq_latex(eq)
%OE_EQ_LATEX Convert model equation text to LaTeX math.
%   L = OE_EQ_LATEX(EQ) rewrites the equation syntax returned by the model
%   API as LaTeX for display:
%       MNEM:GROUP          -> \mathrm{MNEM:GROUP}
%       X:G[-1]             -> X:G with subscript t-1 (leads: t+1)
%       &X:G                -> \varepsilon_{X:G} (equation residual)
%       LOG( LN( DLOG( EXP( DIFF( D(  -> \log, \Delta\log, \exp, \Delta
%       *  and  ^n          -> \cdot  and  ^{n}
%   Other functions keep their names. Characters that break LaTeX math
%   (& % # $) are escaped. The text is not checked for being a valid
%   equation.
%
%   Example:
%       oe_eq_latex('DLOG(AAA:ALPHA) = 0.5 * DLOG(BBB:ALPHA[-1]) + &AAA:ALPHA')
%
%   See also OE_EQUATIONS.

if isempty(eq)
    L = '';
    return
end
s = strtrim(char(eq));
% One token pass, so function names are not rewritten twice:
% optional &, NAME[:GROUP], optional [lag], optional opening parenthesis.
% Named top-level groups only: regexp does not report tokens captured
% inside an optional group, and drops unmatched positional tokens.
pat = ['(?<amp>&?)(?<name>[A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?)' ...
    '(?<lag>\[\s*[+-]?\d+\s*\])?(?<paren>\()?'];
[toks, splits] = regexp(s, pat, 'names', 'split');
out = splits{1};
for i = 1:numel(toks)
    t = toks(i);
    lag = regexprep(fld(t, 'lag'), '[\[\]\s]', '');
    out = [out tok2tex(fld(t, 'amp'), fld(t, 'name'), lag, fld(t, 'paren')) splits{i + 1}]; %#ok<AGROW>
end
out = regexprep(out, '\s*\*\s*', ' \\cdot ');
out = regexprep(out, '\^\s*([A-Za-z0-9.]+)', '^{$1}');
out = regexprep(out, '(?<!\\)&', '\\&');
out = regexprep(out, '(?<!\\)%', '\\%');
out = regexprep(out, '(?<!\\)#', '\\#');
out = regexprep(out, '(?<!\\)\$', '\\$');
L = out;
end

function out = tok2tex(amp, name, lag, paren)
% A name directly followed by '(' is a function call.
if ~isempty(paren) && isempty(amp) && isempty(lag)
    switch upper(name)
        case {'LOG', 'LN'}
            out = '\log(';
            return
        case 'DLOG'
            out = '\Delta\log(';
            return
        case 'EXP'
            out = '\exp(';
            return
        case {'DIFF', 'D'}
            out = '\Delta(';
            return
    end
end
base = ['\mathrm{' strrep(name, '_', '\_') '}'];
if ~isempty(amp)
    base = ['\varepsilon_{' base '}'];
end
if ~isempty(lag)
    if any(lag(1) == '+-')
        sub = lag;
    else
        sub = ['-' lag];
    end
    if ~isempty(amp)
        base = ['{' base '}_{t' sub '}'];
    else
        base = [base '_{t' sub '}'];
    end
end
out = [base paren];
end

function v = fld(t, name)
% Value of a named token, '' when the group did not take part in the match.
v = '';
if isfield(t, name) && ~isempty(t.(name))
    v = char(t.(name));
end
end
