using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Kavita.Database.Migrations
{
    /// <inheritdoc />
    public partial class AddWantToFind : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "AppUserWantToFind",
                columns: table => new
                {
                    Id = table.Column<int>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Title = table.Column<string>(type: "TEXT", maxLength: 256, nullable: false),
                    Authors = table.Column<string>(type: "TEXT", maxLength: 1024, nullable: false),
                    Summary = table.Column<string>(type: "TEXT", nullable: true),
                    Isbn = table.Column<string>(type: "TEXT", maxLength: 64, nullable: true),
                    ExternalId = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    CoverUrl = table.Column<string>(type: "TEXT", maxLength: 2048, nullable: true),
                    SourceUrl = table.Column<string>(type: "TEXT", maxLength: 2048, nullable: true),
                    Notes = table.Column<string>(type: "TEXT", nullable: true),
                    Created = table.Column<DateTime>(type: "TEXT", nullable: false),
                    CreatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    LastModified = table.Column<DateTime>(type: "TEXT", nullable: false),
                    LastModifiedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    AppUserId = table.Column<int>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AppUserWantToFind", x => x.Id);
                    table.ForeignKey(
                        name: "FK_AppUserWantToFind_AspNetUsers_AppUserId",
                        column: x => x.AppUserId,
                        principalTable: "AspNetUsers",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_AppUserWantToFind_AppUserId",
                table: "AppUserWantToFind",
                column: "AppUserId");

            migrationBuilder.Sql("""
                INSERT INTO AppUserSideNavStream (Name, IsProvided, "Order", StreamType, Visible, AppUserId)
                SELECT 'want-to-find', 1,
                       COALESCE((SELECT MAX(existing."Order") + 1
                                 FROM AppUserSideNavStream existing
                                 WHERE existing.AppUserId = users.Id), 1),
                       10, 1, users.Id
                FROM AspNetUsers users
                WHERE NOT EXISTS (
                    SELECT 1 FROM AppUserSideNavStream existing
                    WHERE existing.AppUserId = users.Id AND existing.StreamType = 10
                );
                """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DELETE FROM AppUserSideNavStream WHERE StreamType = 10 AND IsProvided = 1;");

            migrationBuilder.DropTable(
                name: "AppUserWantToFind");
        }
    }
}
