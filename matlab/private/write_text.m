function write_text(file, txt)
%WRITE_TEXT Write char text to a UTF-8 file, creating the folder if needed (private helper).

folder = fileparts(file);
if ~isempty(folder) && ~isfolder(folder)
    mkdir(folder);
end
fid = fopen(file, 'w', 'n', 'UTF-8');
if fid < 0
    error('oe:io', 'Could not open "%s" for writing.', file);
end
closer = onCleanup(@() fclose(fid));
% '%s' writes backslashes and percent signs literally.
fprintf(fid, '%s', txt);
clear closer
end
