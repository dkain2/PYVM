<style>
.table {width:100%; border:1px solid #CCCCCC; border-collapse:collapse; font-size:11px; border-radius:5px; overflow:hidden;}
.header {background-color:#F2F2F2; color:black; border: 0.1px solid #CCCCCC; text-align:center; border-collapse:collapse;}
.cell {text-align:center;  border: 0.1px solid #CCCCCC; border-collapse:collapse;}
.technical-details-table {width:100%; font-size:14px;}
</style>

{{#column1}}
<table class="table">
  <tr>
    {{#column1}}
    <th class="header" {{#column1Width}}style="width:{{column1Width}}%"{{/column1Width}}>{{column1}}</th>
    {{/column1}}
    {{#column2}}
    <th class="header" {{#column2Width}}style="width:{{column2Width}}%"{{/column2Width}}>{{column2}}</th>
    {{/column2}}
    {{#column3}}
    <th class="header" {{#column3Width}}style="width:{{column3Width}}%"{{/column3Width}}>{{column3}}</th>
    {{/column3}}
    {{#column4}}
    <th class="header" {{#column4Width}}style="width:{{column4Width}}%"{{/column4Width}}>{{column4}}</th>
    {{/column4}}
    {{#column5}}
    <th class="header" {{#column5Width}}style="width:{{column5Width}}%"{{/column5Width}}>{{column5}}</th>
    {{/column5}}
  </tr>

  {{#ErrorList}}
  {{#value1}}
  <tr>
    {{#column1}}
    <td class="cell" style="{{#column1Bold}}font-weight:bold;{{/column1Bold}}{{#column1Color}}color: {{column1Color}};{{/column1Color}}">{{#url1}}<a href="{{url1}}">{{/url1}}{{value1}}{{#url1}}</a>{{/url1}}</td>
    {{/column1}}
    {{#column2}}
    <td class="cell" style="{{#column2Bold}}font-weight:bold;{{/column2Bold}}{{#column2Color}}color: {{column2Color}};{{/column2Color}}">{{#url2}}<a href="{{url2}}">{{/url2}}{{value2}}{{#url2}}</a>{{/url2}}</td>
    {{/column2}}
    {{#column3}}
    <td class="cell" style="{{#column3Bold}}font-weight:bold;{{/column3Bold}}{{#column3Color}}color: {{column3Color}};{{/column3Color}}">{{#url3}}<a href="{{url3}}">{{/url3}}{{value3}}{{#url3}}</a>{{/url3}}</td>
    {{/column3}}
    {{#column4}}
    <td class="cell" style="{{#column4Bold}}font-weight:bold;{{/column4Bold}}{{#column4Color}}color: {{column4Color}};{{/column4Color}}">{{#url4}}<a href="{{url4}}">{{/url4}}{{value4}}{{#url4}}</a>{{/url4}}</td>
    {{/column4}}
    {{#column5}}
    <td class="cell" style="{{#column5Bold}}font-weight:bold;{{/column5Bold}}{{#column5Color}}color: {{column5Color}};{{/column5Color}}">{{#url5}}<a href="{{url5}}">{{/url5}}{{value5}}{{#url5}}</a>{{/url5}}</td>
    {{/column5}}
  </tr>
  {{/value1}}
  {{/ErrorList}}
</table>
{{/column1}}

<div class="tech-error-details">
  <h4 style="text-align:left;">Technical Details</h4>
  <table class="technical-details-table">
    {{#Source_System}}<tr><th>Source System</th><td>: {{Source_System}}</td></tr>{{/Source_System}}
    {{#Target_System}}<tr><th>Target System</th><td>: {{Target_System}}</td></tr>{{/Target_System}}
    {{#sourceObject}}<tr><th>Source Object</th><td>: {{sourceObject}}</td></tr>{{/sourceObject}}
   {{#targetObject}}<tr><th>Target Object</th><td>: {{targetObject}}</td></tr>{{/targetObject}}
    {{#Errored_App}}<tr><th>Errored App</th><td>: {{Errored_App}}</td></tr>{{/Errored_App}}
    {{#Errored_Action}}<tr><th>Errored Action</th><td>: {{#stepNumber}}Line {{stepNumber}}: {{/stepNumber}}			{{Errored_Action}}</td></tr>{{/Errored_Action}}
    {{#Error_Time}}<tr><th>Error Time</th><td>: {{Error_Time}}</td></tr>{{/Error_Time}}
    {{#Retry_Count}}<tr><th>Retry Count</th><td>: {{Retry_Count}}</td></tr>{{/Retry_Count}}
	{{#ErrorFIleURL}}<tr><th>Error File</th><td>: <a href="{{ErrorFIleURL}}" target="_blank">View Error File</a></td></tr>{{/ErrorFIleURL}}
  </table>
</div>