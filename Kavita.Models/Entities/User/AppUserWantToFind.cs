#nullable enable
using System;
using System.ComponentModel.DataAnnotations;
using Kavita.Models.Attributes;
using Kavita.Models.Entities.Enums;
using Kavita.Models.Entities.Interfaces;

namespace Kavita.Models.Entities.User;

/// <summary>
/// Metadata for a title the user wants to acquire. This deliberately has no relationship to
/// <see cref="Series"/> so it cannot appear in libraries, collections, search, or OPDS.
/// </summary>
public class AppUserWantToFind : IEntityDate
{
    public int Id { get; set; }

    [MaxLength(256)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public required string Title { get; set; }

    [MaxLength(1024)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public string Authors { get; set; } = string.Empty;

    [ExportScrub(ExportScrubKind.FreeText)]
    public string? Summary { get; set; }

    [MaxLength(64)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public string? Isbn { get; set; }

    [MaxLength(256)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public string? ExternalId { get; set; }

    [MaxLength(2048)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public string? CoverUrl { get; set; }

    [MaxLength(2048)]
    [ExportScrub(ExportScrubKind.FreeText)]
    public string? SourceUrl { get; set; }

    [ExportScrub(ExportScrubKind.FreeText)]
    public string? Notes { get; set; }

    public DateTime Created { get; set; }
    public DateTime CreatedUtc { get; set; }
    public DateTime LastModified { get; set; }
    public DateTime LastModifiedUtc { get; set; }

    public int AppUserId { get; set; }
    public AppUser AppUser { get; set; } = null!;
}
