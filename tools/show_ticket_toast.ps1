param(
    [Parameter(Mandatory = $true)][string]$TicketNumber,
    [Parameter(Mandatory = $true)][string]$Subject,
    [Parameter(Mandatory = $true)][string]$SiteUrl
)

$safeTicket = [System.Security.SecurityElement]::Escape($TicketNumber)
$safeSubject = [System.Security.SecurityElement]::Escape($Subject)
$safeUrl = [System.Security.SecurityElement]::Escape($SiteUrl)
$xml = @"
<toast activationType="protocol" launch="$safeUrl">
  <visual>
    <binding template="ToastGeneric">
      <text>New IT ticket: $safeTicket</text>
      <text>$safeSubject</text>
      <text>$safeUrl</text>
    </binding>
  </visual>
</toast>
"@

[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$document = New-Object Windows.Data.Xml.Dom.XmlDocument
$document.LoadXml($xml)
$notification = [Windows.UI.Notifications.ToastNotification]::new($document)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Microsoft.Windows.PowerShell")
$notifier.Show($notification)
