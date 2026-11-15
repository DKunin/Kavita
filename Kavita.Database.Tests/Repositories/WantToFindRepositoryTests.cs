using System.Linq;
using System.Threading.Tasks;
using Kavita.Models.Builders;
using Kavita.Models.Entities.User;
using Xunit;
using Xunit.Abstractions;

namespace Kavita.Database.Tests.Repositories;

public class WantToFindRepositoryTests(ITestOutputHelper outputHelper) : AbstractDbTest(outputHelper)
{
    [Fact]
    public async Task GetDtosAsync_ReturnsOnlyTheOwnersMetadataItems()
    {
        var (unitOfWork, context, _) = await CreateDatabase();
        var firstUser = new AppUserBuilder("first", "first@example.com").Build();
        var secondUser = new AppUserBuilder("second", "second@example.com").Build();
        context.AppUser.AddRange(firstUser, secondUser);
        await context.SaveChangesAsync();

        context.AppUserWantToFind.AddRange(
            new AppUserWantToFind { AppUserId = firstUser.Id, Title = "Owned", Authors = "Author" },
            new AppUserWantToFind { AppUserId = secondUser.Id, Title = "Private", Authors = "Other" });
        await context.SaveChangesAsync();

        var result = await unitOfWork.WantToFindRepository.GetDtosAsync(firstUser.Id);

        var item = Assert.Single(result);
        Assert.Equal("Owned", item.Title);
        Assert.Equal("Author", item.Authors);
    }

    [Fact]
    public async Task GetAsync_DoesNotReturnAnotherUsersItem()
    {
        var (unitOfWork, context, _) = await CreateDatabase();
        var firstUser = new AppUserBuilder("first", "first@example.com").Build();
        var secondUser = new AppUserBuilder("second", "second@example.com").Build();
        context.AppUser.AddRange(firstUser, secondUser);
        await context.SaveChangesAsync();

        var item = new AppUserWantToFind { AppUserId = firstUser.Id, Title = "Owned" };
        context.AppUserWantToFind.Add(item);
        await context.SaveChangesAsync();

        Assert.Null(await unitOfWork.WantToFindRepository.GetAsync(item.Id, secondUser.Id));
        Assert.NotNull(await unitOfWork.WantToFindRepository.GetAsync(item.Id, firstUser.Id));
    }
}
