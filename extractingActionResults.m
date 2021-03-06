clear all



folderName = 'results/CVPR2012_reverse_slidingwindow_10_150_action_detection_logspace_allowoverlaps/';
logSpaceBool = true;
allowOverlapsBool = true; %false for surroundsuppression
windowSize = 10;
absoluteMaxWindowSize = 150;
reverseSlidingWindowBool = true; % this line untested %false for forward

% folderName = 'results/CVPR2012_reverse_slidingwindow_10_150_action_detection_logspace_surroundsuppression/';
% logSpaceBool = true;
% allowOverlapsBool = false; %false for surroundsuppression
% windowSize = 10;
% absoluteMaxWindowSize = 150;
% reverseSlidingWindowBool = true; % this line untested %false for forward

% folderName = 'results/CVPR2012_reverse_slidingwindow_10_false_action_detection_logspace_surroundsuppression/';
% logSpaceBool = true;
% allowOverlapsBool = false; %false for surroundsuppression
% windowSize = 10;
% absoluteMaxWindowSize = false;
% reverseSlidingWindowBool = true; % this line untested %false for forward

% folderName = 'results/CVPR2012_reverse_slidingwindow_50_false_action_detection_logspace_allowoverlaps/';
% logSpaceBool = true;
% allowOverlapsBool = true; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = false;
% reverseSlidingWindowBool = true; % this line untested %false for forward
% 
% folderName = 'results/CVPR2012_slidingwindow_50_false_action_detection_logspace_allowoverlaps/';
% logSpaceBool = true;
% allowOverlapsBool = true; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = false;
% reverseSlidingWindowBool = false; % this line untested %false for forward
% 
% folderName = 'results/CVPR2012_slidingwindow_50_150_action_detection_logspace_allowoverlaps/';
% logSpaceBool = true;
% allowOverlapsBool = true; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = 150;
% forward sliding window

% folderName = 'results/CVPR2012_slidingwindow_50_150_action_detection_logspace_surroundsuppression/';
% logSpaceBool = true;
% allowOverlapsBool = false; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = 150;
% % forward sliding window 50:150, using logspace surround suppression (NOT allowing overlaps)

% folderName = 'results/CVPR2012_slidingwindow_50_false_action_detection_logspace_surroundsuppression/';
% logSpaceBool = true;
% allowOverlapsBool = false; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = false;
% forward sliding window 50:largest in steps of 50, using logspace surround suppression (NOT allowing overlaps)

% folderName = 'results/CVPR2012_reverse_slidingwindow_50_false_action_detection_logspace_surroundsuppression/';
% logSpaceBool = true;
% allowOverlapsBool = false; %false for surroundsuppression
% windowSize = 50;
% absoluteMaxWindowSize = false;
% reverse sliding window 50:largest in steps of 50, using logspace surround suppression (NOT allowing overlaps)
    
%folderName = 'results/CVPR2012_reverse_slidingwindow_50_150_action_detection_logspace_surroundsuppression/';
% reverse sliding window 50:150 in steps of 50, using logspace surround suppression (NOT allowing overlaps)
% logSpaceBool = true;
% allowOverlapsBool = false;

%folderName = 'results/CVPR2012_reverse_slidingwindow_50_150_action_detection_logspace_allowoverlaps/';
% reverse sliding window 50:150 in steps of 50, using logspace allowing overlaps

%make the init file so python knows it's a module
fid = fopen(strcat(folderName,'__init__.py'),'w');
fclose(fid);

mainDirectory = 'results/CVPR2012_computer_test_action_detection_monday/';
cutPointFileName = 'testingCutPoints.txt';

actionFiles = dir(mainDirectory);
for ind = numel(actionFiles):-1:1
    if ~isempty(regexp(actionFiles(ind).name,'\.', 'once'))
        actionFiles(ind) = []; %TODO: check if works on mac
    end
end
     
errorCheckProbOrder = {'01_benddown'  '02_drink'  '03_makeacall' ...
    '04_pressbutton'  '05_standing'  '06_throwtrash' '07_usecomputer'};

countMissingSkeletons = 0;
for ind = 1:numel(actionFiles)
    
    %if strcmp(actionFiles(ind).name, 'light_8_screen_50_9404') % ADDED THIS
    disp('-------------------------------------------------------')
    singleFile = actionFiles(ind);
    exampleName = singleFile.name;
    locationFolder = strcat(mainDirectory, singleFile.name);
    nFiles = numel(dir(locationFolder));
    if nFiles == 2
        disp(['Missing Results: ' singleFile.name]);
        countMissingSkeletons = countMissingSkeletons + 1;
    else
        disp(['Processing Results: ' singleFile.name]);
        tmpMatFile = load(strcat(mainDirectory, singleFile.name, '/act_parse.mat'));
        
        %test order of probs
        if ~isequal(errorCheckProbOrder, tmpMatFile.act_parse(1).act_prob.act)
            error('wrong order')
        end
        
        
        individualFrames = tmpMatFile.act_parse; 
            % struct array of individual probabilities for each frame.
            % individualFrames(1).frame_ind  <- note: not in order!
            %                    .act_prob (.prob: 7x1 double
            %                               .act: 7x1 cell)
        


        %pingOutputs = tmpMatFile.action;
            % struct array of detections 
            % pingOutputs(1).class <- in errorCheckProbOrder
            %               .prob <- probability of class; 7x1 double
            %               .cutPoint <- cell with frame of cut point
            %                            if empty, then is for whole scene

        cutPoints = getCutPoints(exampleName, cutPointFileName);
        
%         for singleSegmentNumber = 1:(numel(cutPoints)-1)
%             % do sliding window
%             startFrame = cutPoints(singleSegmentNumber);
%             endFrame = cutPoints(singleSegmentNumber+1);
%             disp([startFrame endFrame]);
%             results = slidingWindow(startFrame,endFrame,individualFrames)
%             %unique(results(4,:))
%             %pause
%         end
            
        % do the entire window
        disp(cutPoints);
        results = slidingWindow(cutPoints(1),cutPoints(end),individualFrames, logSpaceBool, ...
            allowOverlapsBool, windowSize, absoluteMaxWindowSize, reverseSlidingWindowBool)
        writeTemporalParses(results,exampleName,folderName);
        %pause
        
        
        % TODO: need to catch empty results...  happens if no such
        % skeletons for those frames
        
                                      
    end
    %end % ADDED THIS
end
